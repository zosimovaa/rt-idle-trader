"""import numpy as np
import time
from threading import Thread, Lock
import logging

from db import ClickHouseConnector

from core import CoreError

from dataset_tools import DataPointFactoryBasic
from dataset_tools import DataPointFactoryError

from data_providers import TradeDataProvider, TradeDataProviderError
from trader import ModelProviderRest, ModelProviderError
from trader import ActionLogger, ActionLoggerError


def path_constructor(model_config):
    gen = str(model_config["alias"].get("gen"))
    period = str(model_config["alias"].get("period"))
    name = str(model_config["alias"].get("name"))
    api_path = "/".join(["", gen, period, name])
    return api_path


class IdleTrader:
    MULTIPLE = 60
    ERROR_TIMEOUT = 5

    def __init__(self, alias, core, config, db_provider_config):
        self.alias = alias
        self.log = logging.getLogger("{0}.{1}.{2}".format(__name__, self.__class__.__name__, self.alias))

        self.update_period = config["update"]
        self.model_config = config["model"]
        self.observation_config = config["observation"]
        self.pairs_list = config["pairs"]
        self.db_provider_config = db_provider_config

        host = self.model_config.get("host")
        path = path_constructor(self.model_config)

        self.model_provider = ModelProviderRest(host, path)
        self.db_provider = None
        self.tickers = []

        for pair in self.pairs_list:
            ticker = core(alias=pair)
            #ticker.reset(buffer_len=self.observation_config.get("n_observation_points"))
            ticker.context.set("status", "init")
            self.tickers.append(ticker)

        self.n_observation_points = self.observation_config["n_observation_points"]
        self.n_future_points = self.observation_config["n_future_points"]
        self.n_total_points = self.n_observation_points + self.n_future_points

        self.lock = Lock()

        self.log.info("IdleTrader has been initialized")
        self.log.debug("Model_config: {0}".format(str(self.model_config)))

        self.main_thread = None

    def start(self):
        self.main_thread = Thread(target=self.main, daemon=True)
        self.main_thread.start()
        self.log.warning("Trader process started")

    def main(self):
        self.log.warning("Main cycle entry")
        while True:
            try:
                self.log.debug("Step 0 - Establish connection")
                with ClickHouseConnector(self.db_provider_config) as provider:

                    # Step 0 - init
                    data_provider = TradeDataProvider(provider)
                    action_logger = ActionLogger(provider, self)

                    # основной цикл
                    while True:
                        self.log.info("=============================================================")
                        # Step 1 - Получаем данные по всем парам. Ошибка здесь останавливает весь процесс.
                        # TradeDataProviderError

                        ts_start = time.time()
                        ts = int(np.floor(ts_start/self.MULTIPLE)*self.MULTIPLE)

                        self.log.debug("Step 1 - Update the tickers data for ts {0}".format(ts))
                        period = self.model_config["alias"].get("period")
                        tickers_data = data_provider.get(
                            ts, period, self.n_total_points, pairs_list=self.pairs_list
                        )

                        # no exception
                        datapoint_factory = DataPointFactoryBasic(
                            ts, tickers_data, self.n_observation_points, self.n_future_points, self.update_period
                        )
                        # перебираем core
                        for ticker in self.tickers:
                            self.log.debug("--------------------------------------------------------")
                            try:
                                # Step 2 - get datapoint
                                # DataPointFactoryError, DataShapeError, DataExpiredError
                                self.log.debug("[{0}] Step 2 - Create datapoint".format(ticker.alias))

                                data_point = datapoint_factory.get_data_point(ticker.alias)
                                status = ticker.context.get("status")
                                if status == "init":
                                    ticker.reset(data_point=data_point)

                                # Step 3 - create observation_builder
                                # CoreError
                                self.log.debug("[{0}] Step 3 - Create observation_builder".format(ticker.alias))
                                with self.lock:
                                    observation = ticker.get_observation(data_point=data_point)

                                # Step 4 - predict action
                                # ModelProviderError
                                self.log.debug("[{0}] Step 4 - Predict action".format(ticker.alias))
                                action = self.model_provider.predict(observation)
                                self.log.debug("Action predicted: {0}".format( action))


                                # Step 5 - apply action and get result
                                # CoreError
                                self.log.debug("[{0}] Step 5 - Apply action".format(ticker.alias))
                                with self.lock:
                                    reward, action_result = ticker.apply_action(action)
                                    self.log.debug("Action applied | reward: {0:.4f}".format(reward))
                                    self.log.debug("Action type returned {0}".format(type(action_result)))

                                ticker.context.set("status", "ok")

                                # Step 6 - save result
                                # ActionLoggerError
                                self.log.debug("[{0}] Step 6 - Log action".format(ticker.alias))
                                action_logger.process(action_result, ticker.alias)

                                # Step  - log result
                                if action == 1:
                                    profit = ticker.context.get("profit", domain="Trade")
                                    self.log.info("{0:>12} Open [{1:.4f}]".format(ticker.alias, profit))

                                if action == 2:
                                    profit = ticker.context.get("profit", domain="Trade")
                                    self.log.info("{0:>12} Hold [{1:.4f}]".format(ticker.alias, profit))

                                if action == 3:
                                    self.log.warning(
                                        "{0:>12} Closed [{1:.4f}]".format(ticker.alias, action_result.profit))

                            # обработка ошибок по конкретной паре
                            except (CoreError, DataPointFactoryError, ModelProviderError) as e:
                                # пропускаем текущий цикл, пару помечаем как ошибочную
                                ticker.context.set("status", "error")
                                self.log.exception(e)
                                pass

                            except ActionLoggerError as e:
                                #  пару помечаем как варнинг
                                ticker.context.set("status", "warning")
                                self.log.exception(e)
                                pass

                        # Step 7 - sleep
                        sleep_time = self.update_period - (time.time() - ts_start)
                        self.log.debug("Step 7 - sleep time: {0:.4}".format(sleep_time))
                        time.sleep(sleep_time)

            # обработка ошибок, валящих весь процесс трейдера
            except (TradeDataProviderError, Exception) as e:
                for ticker in self.tickers:
                    ticker.context.set("status", "error")
                self.log.exception(e)

            finally:
                self.log.warning("Timeout before new cycle ")
                time.sleep(self.ERROR_TIMEOUT)
"""