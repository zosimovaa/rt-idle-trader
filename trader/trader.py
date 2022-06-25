"""
Трейдер реализует необходимый пайплайн для работы на бирже:
    - получение состояния биржи
    - формирование observation
    - запрос предсказания
    - действие на бирже
    - сохранение результата

Процесс получения данных


# todo добаивть в логи алиас трейдера
# todo добавить команду закрытия сделки
# todo перенести удаление тикеров в конец цикла




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

from data_point import DataPointFactory, DataPointFactoryError, DataPointError


logger = logging.getLogger(__name__)


class Trader(BasicApplication):
    MULTIPLE = 60
    ERROR_TIMEOUT = 5
    CONFIG_FILE_NAME = "trader_config.yml"
    DELAY = 5
    CLOSE_ACTION_CODE = 3

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

        logger.warning("Trader {0} initialized".format(alias))

        self.config_path = os.path.join(self.models_path, alias, self.CONFIG_FILE_NAME)
        logger.debug(self.config_path)
        self.model_path = os.path.join(self.models_path, alias)
        logger.debug(self.model_path)

        BasicApplication.__init__(self, config_path=self.config_path)

        self.tickers = dict()
        self.data_provider = None
        self.action_logger = None
        self.model_provider = None
        logger.critical("Trader {0} created".format(self.alias))

    def register_tickers(self, pairs_list=[]):
        """ Метод инициализирует пары по списку из конфига на нужном ядре"""
        core_class = getattr(core, self.config_manager.get_config().get("core"))
        current_pairs_list = list(self.tickers.keys())
        for pair in pairs_list:
            if pair not in current_pairs_list:
                self.tickers[pair] = core_class()
                self.tickers[pair].context.set("status", "init")
                logger.warning("New ticker created for pair {0} ".format(pair))

    def clean_up_tickers(self, pairs_list=[]):
        """ Метод инициализирует пары по списку из конфига на нужном ядре"""
        current_pairs_list = list(self.tickers.keys())
        for pair in current_pairs_list:
            if pair not in pairs_list:
                is_open = self.tickers[pair].context.get("is_open")
                if is_open:
                    reward, action_result = self.tickers[pair].apply_action(self.CLOSE_ACTION_CODE)
                    logger.warning("Pair {0} - trade closed before deleting".format(pair))

                del self.tickers[pair]
                logger.warning("Pair {0} deleted from tickers list".format(pair))

    def run(self):
        while True:
            try:
                logger.critical("{0}: Trader main cycle starting...".format(self.alias))
                with ClickHouseConnector(self.db_config) as conn:
                    self.data_provider = DbDataProvider(conn)
                    self.action_logger = ActionLogger(conn, self)

                    while True:
                        # New cycle start
                        ts = time.time()
                        config = self.config_manager.get_config()
                        logger.warning("{0}: New cycle at timestamp {1}".format(self.alias, ts))

                        # Check exit condition
                        if self.halt.is_set():
                            logger.error("break")
                            break

                        # Init or update trader config
                        config_hash = self.get_hash(config)
                        if self.current_config_hash != config_hash:
                            pairs_list = config.get("pairs_list")
                            self.register_tickers(pairs_list=pairs_list)
                            self.clean_up_tickers(pairs_list=pairs_list)

                            model_path = os.path.join(self.models_path, self.alias)
                            self.model_provider = FileModelProvider(model_path)

                            self.current_config_hash = config_hash
                            logger.warning("{0}: Common step - Trader config updated".format(self.alias))

                        # Step 1 - Get the data
                        observation_cfg = config.get("observation")
                        period = observation_cfg["period"]
                        n_observation_points = observation_cfg["n_observation_points"]
                        n_future_points = observation_cfg["n_future_points"]
                        n_points = n_observation_points + n_future_points

                        dataset = self.data_provider.get_by_periods(ts, period, n_points)
                        logger.info("{0} Common step - dataset downloaded with shape {1}".format(self.alias, dataset.shape))

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
                                logger.debug(
                                    "{0}: [{1}] Step 1 - Datapoint factory created".format(self.alias, key))

                                # Step 2 - Create datapoint
                                data_point = datapoint_factory.get_current_step()

                                if self.tickers[key].context.get("status") == "init":
                                    self.tickers[key].reset(data_point=data_point)

                                logger.debug(
                                    "{0}: [{1}] Step 2 - Datapoint created".format(self.alias, key))

                                # Step 3 - Create observation_builder. Raise CoreError
                                observation = self.tickers[key].get_observation(data_point=data_point)
                                logger.debug(
                                    "{0}: [{1}] Step 3 - Observation created".format(self.alias, key))

                                # Step 4 - predict action. Raise ModelProviderError
                                action = self.model_provider.predict(observation)
                                logger.debug(
                                    "{0}: [{1}] Step 4 - Action predicted {2}".format(self.alias, key, action))

                                # Step 5 - apply action and get result& Raise CoreError
                                reward, action_result = self.tickers[key].apply_action(action)
                                self.tickers[key].context.set("status", "ok")
                                logger.debug(
                                    "{0}: [{1}] Step 5 - Action applied with reward {2}".format(self.alias, key, reward))

                                # Step 6 - save result
                                # ActionLoggerError
                                self.action_logger.process(action_result, self.tickers[key], key)
                                logger.debug(
                                    "{0}: [{1}] Step 6 - Action {2} logged".format(self.alias, key, type(action_result)))

                            # Обработка ошибок по конкретной паре
                            # Критичное
                            except (CoreError, DataPointFactoryError, DataPointError) as e:
                                # пропускаем текущий цикл, пару помечаем как ошибочную
                                self.tickers[key].context.set("status", "error")
                                logger.exception(e)

                            # Не критичное
                            except ActionLoggerError as e:
                                #  Пару помечаем как варнинг
                                self.tickers[key].context.set("status", "warning")
                                logger.exception(e)

                        # Step 7 - sleep
                        sleep_time = max(1, config.get("update_period") - (time.time() - ts))

                        logger.debug("{0}: Step 7 - sleep time: {1:.4f}".format(self.alias, sleep_time))
                        time.sleep(sleep_time)

            # обработка ошибок, валящих весь процесс трейдера
            except (DataProviderError, ModelProviderError, Exception) as e:
                for key in self.tickers:
                    self.tickers[key].context.set("status", "error")
                logger.critical("Fatal error in trader {0}".format(self.alias))
                logger.critical(e)

            finally:
                logger.warning("{0}: Timeout before new cycle".format(self.alias))
                time.sleep(self.ERROR_TIMEOUT)

            time.sleep(self.DELAY)

    def stop(self):
        self.clean_up_tickers()
        super().stop()
