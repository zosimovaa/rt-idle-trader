import logging

from core import BadAction, TradeAction
from basic_application import with_exception

logger = logging.getLogger(__name__)


class ActionLoggerError(Exception):
    pass


class ActionLogger:
    BA_QUERY = 'insert into bad_actions values'
    TA_QUERY = 'insert into trade_actions values'

    def __init__(self, provider, trader):
        self.provider = provider
        self.trader = trader

    @with_exception(ActionLoggerError)
    def process(self, action_result, ticker, alias):
        self.console_log(action_result, ticker, alias)
        self.db_log(action_result, ticker, alias)

    @staticmethod
    def console_log(action_result, ticker, alias):
        action = ticker.context.get("action", domain="Action")
        if action == 1:
            profit = ticker.context.get("profit", domain="Trade")
            logger.info("{0:>12} Open [{1:.4f}]".format(alias, profit))

        if action == 2:
            profit = ticker.context.get("profit", domain="Trade")
            logger.info("{0:>12} Hold [{1:.4f}]".format(alias, profit))

        if action == 3:
            logger.warning(
                "{0:>12} Closed [{1:.4f}]".format(alias, action_result.profit))

    def db_log(self, action_result, ticker, alias):
        logger.debug("db_log action {1} ({2}) for pair {0}"
                       .format(alias, action_result.__class__.__name__, type(action_result)))

        if isinstance(action_result, BadAction):
            logger.debug("BadAction instance has been passed")
            params = self._build_bad_action_params(action_result, alias)
            self._execute(self.BA_QUERY, params)

        if isinstance(action_result, TradeAction) and not action_result.is_open:
            logger.debug("TradeAction instance has been passed")
            params = self._build_trade_action_params(action_result, alias)
            self._execute(self.TA_QUERY, params)

    def _execute(self, query, data):
        logger.debug("_execute method called")
        logger.debug(query)
        logger.debug(data)
        self.provider.cursor.executemany(query, data)

    def _build_bad_action_params(self, action, pair):
        data = list()
        data.append(str(action.id))

        data.append(str(pair))
        data.append(int(action.ts))
        data.append(str(action.action))
        data.append(bool(action.is_open))

        data.append(str(self.trader.alias))
        data.append("model_ver")
        trader_config = self.trader.config_manager.get_config()
        data.append(str(trader_config["observation"]["period"]))
        data.append(str(self.trader.alias))
        return [data]

    def _build_trade_action_params(self, action, pair):
        data = list()

        data.append(str(action.id))

        data.append(str(pair))

        data.append(float(action.profit))
        data.append(int(action.open_ts))
        data.append(int(action.close_ts))
        data.append(float(action.open_price))
        data.append(float(action.close_price))

        data.append(float(action.__dict__.get("market_fee", 0)))
        data.append(float(action.__dict__.get("trade_volume", 0)))

        data.append(str(self.trader.alias))
        data.append("model_ver")
        trader_config = self.trader.config_manager.get_config()
        data.append(str(trader_config["observation"]["period"]))
        data.append(str(self.trader.alias))
        return [data]
