try:
    from importlib.metadata import PackageNotFoundError, version
    __version__ = version('bazis-bulk')
except PackageNotFoundError:
    __version__ = 'dev'
