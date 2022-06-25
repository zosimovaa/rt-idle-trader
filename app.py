"""
Описание подхода:
 > Базовое приложение
    >> Задачи: Управляет трейдерами исходя из конфига (добавялет, останавливает и удаляет)
    >> Конфиг: стандартный конфиг приложения, путь к директории с моделями
    >> Реализация: на базе BasicApplication

 > Трейдер
    >> Задачи: реализует необходимый пайплай, следит за своим конфигом, перечитывает его
    >> Конфиг: отдельный конфиг файл. Там же конфиг подключения к БД
    >> Реализация: на базе BasicApplication

 > Провайдер
    >> Задачи: реализует доступ к модели для получения предсказания
    >> Конфиг: путь к папке с моделью
    >> Реализация: класс (без BasicApplication)

Сохраняю первоначальный подход к конфигу - путь к папке с моделями.
название папки - алиас модели.
внутри файл конфиг и сама модель

"""
import os
import time
import logging
import traceback

from basic_application import BasicApplication

from trader import Trader


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class IdleTraderApp(BasicApplication):
    NAME = "Idle Trader"
    VERSION = 1.0
    MAX_TIMEOUT = 180
    ERROR_TIMEOUT = 10

    def __init__(self, config_path):
        super().__init__(config_path=config_path)
        self.traders = dict()
        logger.critical("{0} v.{1} started".format(self.NAME, self.VERSION))

    @staticmethod
    def get_models_hash_list(models_path):
        """Получение списка директорий с моделями"""
        dir_list = os.listdir(models_path)
        models_list = []
        for alias in dir_list:
            alias_path = os.path.join(models_path, alias)
            config_path = os.path.join(alias_path, "trader_config.yml")
            model_path = os.path.join(alias_path, "saved_model.pb")
            if os.path.exists(config_path) and os.path.exists(model_path):
                models_list.append(alias)

        logger.debug("Models list: {0}".format(models_list))
        return models_list

    def register_traders(self, traders_list, models_path, db_conf):
        """Создание трейдеров"""
        current_traders_list = list(self.traders.keys())
        for alias in traders_list:
            if alias not in current_traders_list:
                self.traders[alias] = Trader(alias, models_path, db_conf)
                self.traders[alias].start()
                logger.warning("New trader created: {}".format(alias))

    def clean_up_traders(self, traders_list):
        """Удаление трейдеров"""
        current_traders_list = list(self.traders.keys())
        for alias in current_traders_list:
            if alias not in traders_list:
                self.traders[alias].stop()
                del self.traders[alias]
                logger.warning("Trader {0} was deleted".format(alias))

    def run(self):
        while True:
            try:
                # 1. Read config
                runtime_config = self.config_manager.get_config().get("runtime")
                models_path = runtime_config["models_path"]
                db_conf = self.config_manager.get_config().get("db")

                # 2. Update traders
                traders_list = self.get_models_hash_list(models_path)
                self.register_traders(traders_list, models_path, db_conf)
                self.clean_up_traders(traders_list)

                # 3. Check stop signal
                if self.halt.is_set():
                    break

                # 4. Timeout
                time.sleep(runtime_config["models_update_period"])

            except Exception as e:
                logger.critical(e)
                logger.error(traceback.format_exc())

            finally:
                time.sleep(self.ERROR_TIMEOUT)

    def stop(self):
        self.clean_up_traders()
        super().stop()



if __name__ == "__main__":
    env_var = os.getenv("ENV", "TEST")
    if env_var == "PROD":
        config_file_name = "prod.yaml"
    else:
        config_file_name = "test.yaml"

    app = IdleTraderApp(config_file_name)
    app.start()
    app.join()
