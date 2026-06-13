import logging

from wc2026brief.config import Config
from wc2026brief.fetcher import WCFetcher


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = Config()
    fetcher = WCFetcher(config)
    fetcher.run()


if __name__ == "__main__":
    main()
