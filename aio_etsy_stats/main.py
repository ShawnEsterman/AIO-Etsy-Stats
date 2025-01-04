import atexit
import datetime
import json
import logging
import re
import socket
import sys
import textwrap
from datetime import datetime, date, time, timedelta
from os import environ, path
from random import uniform, choice
from time import sleep
from typing import NamedTuple, Optional, Tuple

import Adafruit_IO
import requests
import schedule
from Adafruit_IO.model import Group, Feed
from bs4 import BeautifulSoup
from discord_logging.handler import DiscordHandler
from selenium import webdriver


def get_public_ip():
    response = requests.get('https://api.ipify.org').text
    if response:
        return response


class DummyLogger(object):
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class EtsyStoreStats(NamedTuple):
    """Used to format stats from Etsy store"""
    favorite_count: Optional[int] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    sold_count: Optional[int] = None
    avatar_url: Optional[str] = None
    errors: int = 0


class AIOEtsyStats:
    """Class to store and record stats for Etsy"""
    def __init__(self, shop: str, default_reset_hour: int = 14, scrape_interval_minutes: int = 10,
                 aio_username: str = None, aio_password: str = None,
                 discord_webhook: str = None, discord_avatar_url: str = None):
        self.shop = shop
        self.scrape_url = f"https://www.etsy.com/shop/{shop}/sold"
        self.default_reset_hour = default_reset_hour
        self.scrape_interval_minutes = scrape_interval_minutes

        # Get the current stats just incase this hasn't been set up before or AIO is not used
        self.logger = DummyLogger()  # Temporary
        stats = self.scrape_etsy_stats()

        # region Logging
        logging.basicConfig()
        self.logger = logging.Logger(name=type(self).__name__)

        handler_stdout = logging.StreamHandler(sys.stdout)
        handler_stdout.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handler_stdout.setLevel(logging.DEBUG)
        self.logger.addHandler(handler_stdout)

        if discord_webhook:
            discord_handler = DiscordHandler(
                service_name=type(self).__name__,
                webhook_url=discord_webhook,
                avatar_url=stats.avatar_url or discord_avatar_url,
            )
            discord_handler.setFormatter(logging.Formatter("%(message)s"))
            discord_handler.setLevel(logging.INFO)
            self.logger.addHandler(discord_handler)
        # endregion

        # Now that logger is enabled, log if it was okay
        if stats.errors > 0:
            self.logger.debug(f"Stats were returned with {stats.errors} error(s)")
        else:
            self.logger.debug(f"Initial Stats were returned okay. Example... sold {stats.sold_count}")

        public_ip = get_public_ip()
        self.logger.info(textwrap.dedent(f"""
        {type(self).__name__} for **{self.shop}**
        
        -# Scraping for store metrics on host `{socket.gethostname()}`
        -# Scrapes every {scrape_interval_minutes} minutes
        -# Public IP: {public_ip}
        -# Shawn ❤️ Nicole
        """).strip())

        # region Setup AIO
        if not all([aio_username, aio_password]):
            self.logger.warning("aio_username and/or aio_password were not provided")
        else:
            self.logger.debug(f"Connecting to AIO as {aio_username}")
            # Create aio if username and password were supplied
            self._aio = Adafruit_IO.Client(aio_username, aio_password)
            existing_feed_group = None
            try:
                self.logger.debug("Creating Feed Group and Feeds if missing")
                existing_feed_group = self._aio.groups(self.shop.lower())
            except Exception as e:
                pass
            finally:
                if not existing_feed_group:
                    self.logger.debug(f"Creating Feed Group \"{self.shop}\"")
                    self._aio.create_group(group=Group(name=self.shop, key=self.shop.lower()))

                feeds = [
                    (Feed(name="Daily Order Count", key="daily-order-count"), "0"),
                    (Feed(name="Favorite Count", key="favorite-count"), stats.favorite_count),
                    (Feed(name="Rating", key="rating"), stats.rating),
                    (Feed(name="Rating Count", key="rating-count"), stats.rating_count),
                    (Feed(name="Sold Count", key="sold-count"), stats.sold_count),
                    (Feed(name="_Reset Hour", key="reset-hour"), default_reset_hour),
                    (Feed(name="_Starting Stats", key="starting-stats"), {"first": "run"}),
                ]
                for feed, initial_value in feeds:
                    existing_feed = None
                    try:
                        existing_feed = self._aio.feeds(self._get_feed_name(feed.key))
                    except Exception as e:
                        pass  # No logging
                    finally:
                        if not existing_feed:
                            self.logger.debug(f"Creating feed \"{feed.name}\"")
                            self._aio.create_feed(feed=feed, group_key=self.shop.lower())

                            if initial_value:
                                self._send_aio(feed=feed.key, value=initial_value)
        # endregion

        # region Set class variables to track stats
        self.logger.debug("Loading stats from AIO if they exist otherwise using current stats")
        self.update_total = 0  # Used to count the number of times parsing is performed

        self.favorite_count: int = stats.favorite_count
        self.rating: float = stats.rating
        self.rating_count: int = stats.rating_count
        self.sold_count: int = stats.sold_count
        # The received_aio command will return default_value if the feed doesn't have a value (i.e. this is the first
        # run. So we can get the stats and use them as the default_value
        self.daily_order_count: int = int(self._receive_aio(feed="daily-order-count",
                                                            default_value=0))
        self.reset_hour: int = int(self._receive_aio(feed="reset-hour",
                                                     default_value=default_reset_hour))

        starting_stats = self._get_starting_stats()

        # This can't be obtained from parsing, so if it doesn't exist in AIO default to 0 😓
        self.starting_favorite_count: int = int(starting_stats.get("starting-favorite-count", stats.favorite_count))
        self.starting_rating: float = float(starting_stats.get("starting-rating", stats.rating))
        self.starting_rating_count: int = int(starting_stats.get("starting-rating-count", stats.rating_count))
        self.starting_sold_count: int = int(starting_stats.get("starting-sold-count", stats.sold_count))

        # Load reset timestamp if it was found
        reset_timestamp = starting_stats.get("reset-timestamp")
        if reset_timestamp:
            self.reset_datetime: datetime = datetime.fromtimestamp(float(reset_timestamp))
        else:
            self.reset_datetime: datetime = datetime.now()
        self._validate_reset_hour()

        self._log_current_stats()
        # endregion

        atexit.register(self._atexit)

    def _atexit(self):
        """Log that the client is closing"""
        self.logger.info(textwrap.dedent(f"""
        {type(self).__name__} for **{self.shop}**

        -# Exiting on host `{socket.gethostname()}`
        """).strip())

    def _get_starting_stats(self) -> dict:
        """Gets starting-stats feed and parses the json to dictionary"""
        starting_stats_response = self._receive_aio(feed="starting-stats")
        starting_stats_response = starting_stats_response.replace("\'", "\"")
        return json.loads(starting_stats_response)

    def _get_selenium(self, url: str) -> Tuple[str, str]:
        """Gets webpage content with selenium"""
        driver = None
        content = None
        title = None
        try:
            if path.exists("/usr/bin/geckodriver"):
                firefox_service = webdriver.FirefoxService(executable_path="/usr/bin/geckodriver")
                driver = webdriver.Firefox(service=firefox_service)
            else:
                driver = webdriver.Firefox()

            driver.get(url)
            sleep(2)
            title = driver.title
            content = driver.page_source

            if not content:
                self.logger.debug(f"No content for url {url}. Page title: {driver.title}")

        except Exception as e:
            self.logger.warning("An error occurred getting page with Selenium Firefox")
            self.logger.exception(e)
            raise e
        finally:
            if driver:
                driver.quit()

        return title, content

    def _validate_reset_hour(self):
        """Used to validate that the reset hour is set correctly in the event it is changed on AIO"""
        # Prioritize AIO, but use the environment variable if not available
        desired_reset_hour = int(self._receive_aio(feed="reset-hour", default_value=self.default_reset_hour,
                                                   silent=True))
        if desired_reset_hour:
            # If the server shows the reset_hour different, update it
            if self.reset_hour != desired_reset_hour:
                self.logger.info(f"Changing reset hour from {self.reset_hour} to {desired_reset_hour}")
                self.reset_hour = desired_reset_hour

        # If the reset hour isn't correct for the existing datetime, update it
        if any([self.reset_datetime.hour != self.reset_hour, self.reset_datetime.minute != 0]):
            new_reset_datetime = self.reset_datetime
            new_reset_datetime = new_reset_datetime.replace(hour=self.reset_hour, minute=0)
            self.logger.info(f"Changing reset time from {self.reset_datetime} to {new_reset_datetime}")
            self.reset_datetime = new_reset_datetime
            self._send_starting_stats()

    def _get_feed_name(self, feed: str):
        """Adds the feed group prefix, so you don't have to add it every time"""
        return f"{self.shop.lower()}.{feed}"

    def _send_aio(self, feed: str, value):
        """Helper function to send values to AIO and parse for errors"""
        if self._aio:
            feed = self._get_feed_name(feed=feed)
            
            try:
                self.logger.debug(f"Updating AIO feed {feed} to {value}")
                if isinstance(value, dict):
                    value = str(value)
                _ = self._aio.send_data(feed=feed, value=value)
            except Exception as e:
                self.logger.warning(f"An error occurred updating AIO feed {feed} to {value}")
                self.logger.exception(e)

    def _receive_aio(self, feed: str, default_value: object = None, silent: bool = False):
        """Helper method to get values from aio"""
        return_val = default_value
        if self._aio:
            feed = self._get_feed_name(feed=feed)
            
            try:
                response = self._aio.receive(feed=feed)
                if not silent:
                    self.logger.debug(f"AIO Feed {feed} has a value of {response.value}")
                return response.value
            except Exception as e:
                self.logger.warning(f"An error occurred getting AIO feed {feed} value")
                self.logger.exception(e)
        return return_val

    def _reset_counts(self) -> None:
        """Reset counts and update AIO"""
        # Update all things to be equal to current stats
        self.daily_order_count = 0
        self.starting_favorite_count = self.favorite_count
        self.starting_rating = self.rating
        self.starting_rating_count = self.rating_count
        self.starting_sold_count = self.sold_count

        updates = [
            ("daily-order-count", self.daily_order_count),
            ("favorite-count", self.favorite_count),
            ("rating", self.rating),
            ("rating-count", self.rating_count),
            ("sold-count", self.sold_count),
        ]
        for feed, value in updates:
            self._send_aio(feed=feed, value=value)

        # We need to get a new reset date and set the values for the starting values
        self.reset_datetime = datetime.combine(date.today(), time(hour=self.reset_hour, minute=0,
                                                                  second=0, microsecond=0))
        if self.reset_datetime < datetime.now():
            # Just incase you start this app after the current day's reset timer hit
            self.reset_datetime = self.reset_datetime + timedelta(days=1)
        self.logger.info(f"Starting counts are reset to current stats. Next reset will occur at {self.reset_datetime}")
        self._send_starting_stats()  # Send it when it is updated on the class instance

    def _send_starting_stats(self) -> None:
        """Sends reset info as dict/json. This is loaded if the script restarts so things aren't 0 if between resets"""
        self._send_aio(feed="starting-stats", value={
            "starting-favorite-count": self.starting_favorite_count,
            "starting-rating": self.starting_rating,
            "starting-rating-count": self.starting_rating_count,
            "starting-sold-count": self.starting_sold_count,
            "reset-timestamp": self.reset_datetime.timestamp()
        })

    def scrape_etsy_stats(self) -> EtsyStoreStats:
        """Used to scrape the Etsy store page. Will need to be modified if they change the way the site layout is"""
        favorite_count = None
        rating = None
        rating_count = None
        sold_count = None
        avatar_url = None
        errors = 0

        soup = None
        title, page_source = self._get_selenium(url=self.scrape_url)

        if page_source:
            try:
                soup = BeautifulSoup(page_source, "html.parser")
            except Exception as e:
                self.logger.warning("Unable to have BeautifulSoup parse page source")
                self.logger.exception(e)
                errors += 1
        else:
            self.logger.warning("Nothing was returned for page source")
            errors = 1

        if soup:
            # region Favorite Count
            try:
                scripts = soup.find_all(name="script")
                for script in scripts:
                    match = re.search(r".*\"num_favorers\":(\d+),.*", script.get_text().strip())
                    if match:
                        favorite_count = int(match[1])
            except Exception as e:
                self.logger.warning("Error occurred parsing for Favorite Count")
                self.logger.exception(e)
                self.logger.warning(f"Page Source:\n{page_source}")
                errors += 1
            # endregion

            # region Rating
            found_rating = None
            try:
                found_rating = soup.find(name="input", attrs={"name": "rating"})
                if found_rating:
                    rating = float(found_rating.get("value"))
            except Exception as e:
                self.logger.warning("Error occurred parsing for Rating")
                self.logger.exception(e)
                errors += 1
            # endregion

            # region Rating Count
            if found_rating:
                try:
                    found_ratings = found_rating.parent.parent.find(string=re.compile(r"\(\d+\)"))
                    if found_ratings:
                        rating_count = int(found_ratings.strip().replace("(", "").replace(")", ""))
                except Exception as e:
                    self.logger.warning("Error occurred parsing for Rating Count")
                    self.logger.exception(e)
                    errors += 1
            # endregion

            # region Sold Count
            try:
                found_sales = soup.find(string=re.compile("([0-9,]) Sales"))
                if found_sales:
                    sold_count = int(found_sales.get_text().strip().replace(" Sales", "").replace(",", ""))
            except Exception as e:
                self.logger.warning("Error occurred parsing for Sold Count")
                self.logger.exception(e)
                errors += 1
            # endregion

            # region Avatar URL
            try:
                found_avatar_div = soup.find(name="div", attrs={"class": "condensed-header-shop-image"})
                if found_avatar_div:
                    found_avatar_img = found_avatar_div.findChild("img")
                    if "src" in found_avatar_img.attrs:
                        avatar_url = found_avatar_img.attrs["src"]
                    else:
                        self.logger.debug("Unable to get Avatar URL")
            except Exception as e:
                errors += 1
            # endregion

        return EtsyStoreStats(favorite_count=favorite_count, rating=rating, rating_count=rating_count, 
                              sold_count=sold_count, avatar_url=avatar_url, errors=errors)

    def _log_current_stats(self):
        """Log current stats to debug"""
        self.logger.debug("Logging current stats")
        self.logger.debug(str(dict([
            ("daily-order-count", self.daily_order_count),
            ("favorite-count", self.favorite_count), ("starting-favorite-count", self.starting_favorite_count),
            ("rating", self.rating), ("starting-rating", self.starting_rating),
            ("rating-count", self.rating_count), ("starting-rating-count", self.starting_rating_count),
            ("sold-count", self.sold_count), ("starting-sold-count", self.starting_sold_count),
            ("reset-hour", self.reset_hour), ("reset-datetime", self.reset_datetime)
        ])))

    def collect_and_publish(self) -> None:
        """Handles the main portion of this class and runs the helper functions in the main order"""
        self.update_total += 1
        self.logger.debug(f"Checking {self.shop} for updates. Count: {self.update_total}")

        # Every time you run, check the reset hour to see if it changed
        self._validate_reset_hour()

        # Get Etsy stats
        stats = self.scrape_etsy_stats()
        if (self.update_total % 30) == 0:
            self._log_current_stats()

        # If we passed reset_datetime, process the reset using the current stats
        if datetime.now() > self.reset_datetime:
            self.logger.info(f"Reset time of {self.reset_datetime} has been passed")
            self._reset_counts()

        # region Process Stats
        # Favorites
        if all([isinstance(stats.favorite_count, int), self.favorite_count != stats.favorite_count]):
            self.logger.info(textwrap.dedent(f"""
            Favorites for **{self.shop}**

            -# Count changed `{self.favorite_count:,}` -> `{stats.favorite_count:,}`
            """).strip())
            self.favorite_count = stats.favorite_count
            self._send_aio(feed="favorite-count", value=self.favorite_count)

        # Rating
        if all([isinstance(stats.rating, float), self.rating != stats.rating]) or \
                all([isinstance(stats.rating_count, int), self.rating_count != stats.rating_count]):

            message = textwrap.dedent(f"""
            Rating for **{self.shop}**

            -# Count changed `{self.rating_count:,}` -> `{stats.rating_count:,}`
            """).strip()
            self.rating_count = stats.rating_count
            self._send_aio(feed="rating-count", value=self.rating_count)

            # If rating did not change, do not say it did
            rating_change = round((stats.rating - self.rating), 4)
            if rating_change == 0.0:
                message += f"\n-# Overall is `{self.rating:.4f}`"
            else:
                message += f"\n-# Overall changed `{self.rating:.4f}` -> `{stats.rating:.4f}`"
                self.rating = stats.rating
                self._send_aio(feed="rating", value=self.rating)

            # If it goes up, normal
            if rating_change >= 0:
                self.logger.info(message.strip())
            else:
                # If it goes down, warning
                self.logger.warning(message.strip())

        # Sold
        if all([isinstance(stats.sold_count, int), self.sold_count != stats.sold_count]):
            # Create message
            message = textwrap.dedent(f"""
            Orders for **{self.shop}**

            -# Sold Count changed `{self.sold_count:,}` -> `{stats.sold_count:,}`
            """).strip()
            if self.sold_count < stats.sold_count:
                message += f"\n-# Daily Order Count changed from `{self.daily_order_count:,}` -> " \
                           f"`{(self.daily_order_count + 1):,}`"
                self.daily_order_count += 1
                self._send_aio(feed="daily-order-count", value=self.daily_order_count)
            else:
                message += f"\n-# Daily Order Count is `{self.daily_order_count:,}`"
            self.logger.info(message.strip())

            self.sold_count = stats.sold_count
            self._send_aio(feed="sold-count", value=self.sold_count)
        # endregion

    def _add_scheduled_job(self):
        """Used to add the job. Can be called again if you have to remove it from the schedule"""
        minutes = self.scrape_interval_minutes
        if minutes > 10:
            schedule.every(minutes - 5).to(minutes).minutes.do(self.collect_and_publish)
        else:
            schedule.every(minutes).to(minutes + 5).minutes.do(self.collect_and_publish)

    def main(self):
        """Run this to have this run on a schedule"""
        # Repeat to update the Etsy counts
        self.logger.debug(f"Scrapes will be performed about every {self.scrape_interval_minutes} minute(s)")

        self._add_scheduled_job()
        while True:
            schedule.run_pending()
            # Sleep randomly to avoid scheduled scrapes that get banned
            sleep((uniform(0.45, 0.99) * (self.scrape_interval_minutes * 15)))


if __name__ == "__main__":

    client = AIOEtsyStats(shop=environ.get("ETSY_STORE_NAME"),
                          default_reset_hour=int(environ.get("DEFAULT_RESET_HOUR", 14)),
                          scrape_interval_minutes=int(environ.get("SCRAPE_INTERVAL_MINUTES", 5)),
                          aio_username=environ.get("AIO_USERNAME"),
                          aio_password=environ.get("AIO_PASSWORD"),
                          discord_webhook=environ.get("DISCORD_WEBHOOK"),
                          discord_avatar_url=environ.get("DISCORD_AVATAR_URL"))
    client.main()
