import external_libs

import os
import time
import logging
import logging.config
from threading import Thread, Event
from app_tools import read_config
from trader import Trader


class TraderApp(Thread):
    """Класс реализует основное приложение и запускает трейдеров из конфиг-директории"""
    def __init__(self, cfg):
        Thread.__init__(self, daemon=True)
        self.config = cfg
        self.db_conf = cfg.get("db")
        self.models_path = cfg.get("models_path")
        self.halt = Event()
        self.traders = dict()
        self.log = logging.getLogger(__name__)


    def get_models_hash_list(self):
        """Получение списка директорий с моделями"""
        dir_list = os.listdir(self.models_path)
        models_list = []
        for alias in dir_list:
            alias_path = os.path.join(self.models_path, alias)
            config_path = os.path.join(alias_path, "config.yml")
            if os.path.isdir(alias_path) and os.path.exists(config_path):
                models_list.append(alias)
        self.log.debug("Models list: {0}".format(models_list))
        return models_list

    def register_traders(self, traders_list=[]):
        """Создание трейдеров"""
        current_traders_list = list(self.traders.keys())
        for alias in traders_list:
            if alias not in current_traders_list:
                self.traders[alias] = Trader(alias, self.models_path, self.db_conf)
                self.traders[alias].start()
                self.log.warning("New trader {0} was created".format(alias))

    def clean_up_traders(self, traders_list=[]):
        """Удаление трейдеров"""
        current_traders_list = list(self.traders.keys())
        for alias in current_traders_list:
            if alias not in traders_list:
                self.traders[alias].stop()
                del self.traders[alias]
                self.log.warning("Trader {0} was deleted".format(alias))

    def run(self):
        while True:
            # 1. Update traders
            traders_list = self.get_models_hash_list()
            self.register_traders(traders_list=traders_list)
            self.clean_up_traders(traders_list=traders_list)

            # 2. Check stop signal
            if self.halt.is_set():
                break

            time.sleep(self.config.get("models_update_period"))

    def stop(self):
        """Остановка трейдеров и приложения"""
        self.halt.set()
        self.join()
        self.clean_up_traders()
        self.log.critical("TraderApp stopped")


if __name__ == "__main__":
    config = read_config('config/config2.yml')
    logging.config.dictConfig(config.get("log"))

    app = TraderApp(config)
    app.start()
    app.join()
