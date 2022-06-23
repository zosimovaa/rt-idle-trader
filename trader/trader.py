"""
Трейдер реализует необходимый пайплайн для работы на бирже:
    - получение состояния биржи
    - формирование observation
    - запрос предсказания
    - действие на бирже
    - сохранение результата

Процесс получения данных




"""
import os
import time
import logging
from threading import Lock

from .model_provider import FileModelProvider, ModelProviderError
from .action_logger import ActionLogger, ActionLoggerError

from basic_application import BasicApplication
import core
from core import CoreError

from data_providers import ClickHouseConnector
from data_providers import DbDataProvider, DataProviderError

from data_point import DataPointFactory, DataPointFactoryError


class Trader(BasicApplication):
    MULTIPLE = 60
    ERROR_TIMEOUT = 5
    CONFIG_FILE_NAME = "trader_config.yml"
    MODEL_DIR_NAME = "model"
    DELAY = 5

    def __init__(self, alias, models_path, db_config):
        """
        :param alias: название модели, соответствет названи папки
        :param models_path: путь к моделям
        :param db_config: конфиг для подключения к БД
        """
        self.alias = alias
        self.models_path = models_path
        self.db_config = db_config
        self.lock = Lock()
        self.current_config_hash = None

        self.log = logging.getLogger(__name__)
        self.log.warning("Trader {0} initialized".format(alias))

        self.config_path = os.path.join(self.models_path, alias, self.CONFIG_FILE_NAME)
        self.log.debug(self.config_path)
        self.model_path = os.path.join(self.models_path, alias, self.MODEL_DIR_NAME)
        self.log.debug(self.model_path)

        BasicApplication.__init__(self, config_path=self.config_path)

        self.tickers = dict()
        self.data_provider = None
        self.action_logger = None
        self.model_provider = None



        # self.log = logging.getLogger("{0}.{1}".format(__name__, alias))

    def register_tickers(self, pairs_list):
        """ Метод инициализирует пары по списку из конфига на нужном ядре"""
        core_class = getattr(core, self.config_manager.get_config().get("core"))
        current_pairs_list = list(self.tickers.keys())
        for pair in pairs_list:
            if pair not in current_pairs_list:
                self.tickers[pair] = core_class()
                self.tickers[pair].context.set("status", "init")
                self.log.warning("New ticker created for pair {0} ".format(pair))

    def clean_up_tickers(self, pairs_list):
        """ Метод инициализирует пары по списку из конфига на нужном ядре"""
        current_pairs_list = list(self.tickers.keys())
        for pair in current_pairs_list:
            if pair not in pairs_list:
                del self.tickers[pair]
                self.log.warning("Pair {0} deleted from tickers list".format(pair))

    def run(self):
        self.log.warning("Main trader cycle start")
        while True:
            try:
                self.log.debug("Establish connection")
                with ClickHouseConnector(self.db_config) as conn:
                    self.data_provider = DbDataProvider(conn)
                    self.action_logger = ActionLogger(conn, self)

                    while True:
                        # New cycle start
                        ts = time.time()
                        config = self.config_manager.get_config()
                        self.log.debug("---= New cycle at timestamp {0}=----".format(ts))

                        # Check exit condition
                        if self.halt.is_set():
                            self.log.debug("break")
                            break

                        # Init or update trader config
                        config_hash = self.get_hash(config)
                        if self.current_config_hash != config_hash:
                            pairs_list = config.get("pairs_list")
                            self.register_tickers(pairs_list)
                            self.clean_up_tickers(pairs_list)
                            model_path = os.path.join(self.models_path, self.alias, self.MODEL_DIR_NAME)
                            print(model_path)
                            self.model_provider = FileModelProvider(model_path)
                            self.current_config_hash = config_hash
                            self.log.debug("Common step - Trader config updated")

                        # Step 1 - Get the data
                        observation_cfg = config.get("observation")
                        period = observation_cfg["period"]
                        n_observation_points = observation_cfg["n_observation_points"]
                        n_future_points = observation_cfg["n_future_points"]
                        n_points = n_observation_points + n_future_points

                        dataset = self.data_provider.get_by_periods(ts, period, n_points)
                        self.log.debug("Common step - dataset downloaded with shape {0}".format(dataset.shape))

                        # Handle pairs
                        tickers_list = list(self.tickers.keys())
                        for key in tickers_list:
                            try:
                                # Step 1 - Create datapoint ============================================================
                                pair_dataset = dataset.loc[dataset["pair"] == key]
                                datapoint_factory = DataPointFactory(
                                    dataset=pair_dataset,
                                    period=period,
                                    n_observation_points=n_observation_points,
                                    n_future_points=n_future_points
                                )
                                self.log.debug(
                                    "[{0}] Step 1 - Datapoint factory created".format(key))

                                # Step 2 - Create datapoint
                                data_point = datapoint_factory.get_current_step()

                                if self.tickers[key].context.get("status") == "init":
                                    self.tickers[key].reset(data_point=data_point)

                                self.log.debug(
                                    "[{0}] Step 2 - Datapoint created".format(key))

                                # Step 3 - Create observation_builder. Raise CoreError
                                observation = self.tickers[key].get_observation(data_point=data_point)
                                self.log.debug(
                                    "[{0}] Step 3 - Observation created".format(key))

                                # Step 4 - predict action. Raise ModelProviderError
                                action = self.model_provider.predict(observation)
                                self.log.debug(
                                    "[{0}] Step 4 - Action {1} predicted".format(key, action))

                                # Step 5 - apply action and get result& Raise CoreError
                                reward, action_result = self.tickers[key].apply_action(action)
                                self.tickers[key].context.set("status", "ok")
                                self.log.debug(
                                    "[{0}] Step 5 - Action applied with reward {1}".format(key, reward))

                                # Step 6 - save result
                                # ActionLoggerError
                                self.action_logger.process(action_result, self.tickers[key], key)
                                self.log.debug(
                                    "[{0}] Step 6 - Action {1} logged".format(key, type(action_result)))

                            # обработка ошибок по конкретной паре
                            except (CoreError, DataPointFactoryError, ModelProviderError) as e:
                                # пропускаем текущий цикл, пару помечаем как ошибочную
                                self.tickers[key].context.set("status", "error")
                                self.log.exception(e)

                            except ActionLoggerError as e:
                                #  пару помечаем как варнинг
                                self.tickers[key].context.set("status", "warning")
                                self.log.exception(e)

                        # Step 7 - sleep
                        sleep_time = max(1, config.get("update_period") - (time.time() - ts))

                        self.log.debug("Step 7 - sleep time: {0:.4f}".format(sleep_time))
                        time.sleep(sleep_time)

            # обработка ошибок, валящих весь процесс трейдера
            except (DataProviderError, Exception) as e:
                for key in self.tickers:
                    self.tickers[key].context.set("status", "error")
                self.log.exception(e)

            finally:
                self.log.warning("Timeout before new cycle ")
                time.sleep(self.ERROR_TIMEOUT)

            if self.halt.is_set():
                break

            time.sleep(self.DELAY)

