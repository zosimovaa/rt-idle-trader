"""import yaml
import os
import checksumdir
#from app_tools import with_exception


class ConfigProviderError(Exception):
    pass


class ParamDoesNotExistError(ConfigProviderError):
    pass


class ConfigProvider:
    config_file_name = "config.yml"

    def __init__(self, path):
        self.path = path
        self.config_hash = None
        self.config = None
        self.read_config()

    @with_exception(ConfigProviderError)
    def read_config(self):
        full_path = os.path.join(self.path, self.config_file_name)
        config_hash = checksumdir.dirhash(self.path)
        is_updated = self.config_hash != config_hash
        if is_updated:
            with open(full_path, "r") as stream:
                self.config = yaml.safe_load(stream)
            self.config_hash = config_hash
        return is_updated

    @with_exception(ParamDoesNotExistError)
    def get(self, param):
        val = self.config.get(param)
        return val
"""