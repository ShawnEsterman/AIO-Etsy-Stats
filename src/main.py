import datetime
import json
import logging
import re
import sys
from datetime import datetime, date, time, timedelta
from os import environ
from random import random
from time import sleep
from typing import NamedTuple

import Adafruit_IO
import schedule
from Adafruit_IO.model import Group, Feed
from bs4 import BeautifulSoup
from requests import Session
from requests.adapters import HTTPAdapter


class EtsyStats(NamedTuple):
    """Used to format stats from Etsy store"""
    favorites: int = 0
    rating: float = 0.0
    ratings: int = 0
    sales: int = 0
    errors: int = 0


class EstyStoreStats:
    """Class to store and record stats for Etsy"""
    def __init__(self, shop: str, aio_username: str = None,
                 aio_password: str = None):
        # Shop info
        self.shop = shop
        self.url = f"https://www.etsy.com/shop/{shop}/sold"

        # Logger
        self.logger = logging.Logger(name=__name__)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)

        # Session
        self._session = Session()
        self._session.headers = {
            "User-Agent": "XYZ/3.0",
            "Referer": f"https://www.etsy.com/shop/{self.shop}?ref=sim_anchor",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
                      ",application/signed-exchange;v=b3;q=0.7",

        }
        self._session.mount("https://", HTTPAdapter(max_retries=3))

        # region setup AIO
        if all([aio_username, aio_password]):
            # Create aio if username and password were supplied
            self._aio = Adafruit_IO.Client(aio_username, aio_password)
            existing_feed_group = None
            try:
                existing_feed_group = self._aio.groups(self.shop.lower())
                self.logger.info(f"Connected to Adafruit IO for {aio_username}")
            except Exception as e:
                self.logger.warning(f"Feed Group \"{self.shop}\" does not exist")
            finally:
                if not existing_feed_group:
                    self.logger.warning(f"Feed Group \"{self.shop}\" creating")
                    self._aio.create_group(group=Group(name=self.shop, key=self.shop.lower()))

                feeds = [
                    (Feed(name="_Reset Info", key="reset-info"), {"data": 0}),
                    (Feed(name="_Reset Hour", key="reset-hour"), 22),
                    (Feed(name="_Update Count", key="update-total"), 0),
                    (Feed(name="_Error Count", key="error-count"), 0),
                    (Feed(name="Favorite Change", key="favorites-change"), None),
                    (Feed(name="Rating Change", key="rating-change"), None),
                    (Feed(name="Ratings Change", key="ratings-change"), None),
                    (Feed(name="Sales Change", key="sales-change"), None),
                ]
                for feed, initial_value in feeds:
                    existing_feed = None
                    try:
                        existing_feed = self._aio.feeds(self.get_feed_name(feed.key))
                    except Exception as e:
                        self.logger.warning(f"Feed \"{feed.name}\" does not exist")
                    finally:
                        if not existing_feed:
                            self.logger.info(f"Feed \"{feed.name}\" creating")
                            self._aio.create_feed(feed=feed, group_key=self.shop.lower())

                            if initial_value:
                                self.send_aio(feed=self.get_feed_name(feed.key), value=initial_value)
        # endregion

        # region Set default variables
        # The received_aio command will return None if aio isn't setup or the default value if you provide it
        self.reset_hour: int = int(self.receive_aio(feed=self.get_feed_name("reset-hour"), default_value=22))
        self.update_total: int = int(self.receive_aio(feed=self.get_feed_name("update-total"), default_value=0))
        self.favorites_change: int = int(self.receive_aio(feed=self.get_feed_name("favorites-change"),
                                                          default_value=0))
        self.rating_change: float = float(self.receive_aio(feed=self.get_feed_name("rating-change"), default_value=0.0))
        self.ratings_change: int = int(self.receive_aio(feed=self.get_feed_name("ratings-change"), default_value=0))
        self.sales_change: int = int(self.receive_aio(feed=self.get_feed_name("sales-change"), default_value=0))

        if self._aio:
            reset_info_response = self.receive_aio(feed=self.get_feed_name("reset-info"))
            reset_info_response = reset_info_response.replace("\'", "\"")
            reset_info = json.loads(reset_info_response)
            self.favorites_start: int = int(reset_info.get("favorites-start", 0))
            self.rating_start: float = float(reset_info.get("rating-start", 0.0))
            self.ratings_start: int = int(reset_info.get("ratings-start", 0))
            self.sales_start: int = int(reset_info.get("sales-start", 0))
            self.reset_datetime: datetime = datetime.fromtimestamp(float(reset_info.get("reset-timestamp", datetime.now().timestamp())))
        else:
            self.favorites_start: int = 0
            self.rating_start: float = 0.0
            self.ratings_start: int = 0
            self.sales_start: int = 0
            self.reset_datetime: datetime = datetime.now()
        # endregion

        # Load any existing information at startup
        self.validate_reset_hour()
        self.update_total = int(self.receive_aio(feed=self.get_feed_name("update-total"), default_value=0))
        # Get Etsy.com to make sure its working and you establish cookies
        _ = self._session.get("https://www.etsy.com/")
        # Collect stats at first run
        self.collect_and_publish()

    def validate_reset_hour(self):
        """
        Since reset hour can change, let's make a function we can call to check it and update the
        class
        :return:
        """
        reset_hour_response = self.receive_aio(feed=self.get_feed_name("reset-hour"))
        if reset_hour_response:
            reset_hour_aio_value = int(reset_hour_response)
            # If the server shows the reset_hour different, update it
            if self.reset_hour != reset_hour_aio_value:
                self.logger.info(f"Changing reset hour from {self.reset_hour} to {reset_hour_aio_value}")
                self.reset_hour = reset_hour_aio_value

        # If the reset hour isn't correct for the existing datetime, update it
        if any([self.reset_datetime.hour != self.reset_hour, self.reset_datetime.minute != 0]):
            new_reset_datetime = self.reset_datetime
            new_reset_datetime = new_reset_datetime.replace(hour=self.reset_hour, minute=0)
            self.logger.info(f"Changing reset time from {self.reset_datetime} to {new_reset_datetime}")
            self.reset_datetime = new_reset_datetime
            self.send_reset_info()

    def get_feed_name(self, feed: str):
        """
        Adds the feed group prefix, so you don't have to add it every time
        :param feed:
        :return:
        """
        return f"{self.shop.lower()}.{feed}"

    def send_aio(self, feed: str, value):
        """
        Helper function to send values to aio and parse for errors
        :param feed: Name of feed
        :param value: Value to send
        :return:
        """
        if self._aio:
            try:
                self.logger.debug(f"Updating AIO feed {feed} to {value}")
                if isinstance(value, dict):
                    value = str(value)
                self._aio.send_data(feed=feed, value=value)
            except Exception as e:
                self.logger.warning(f"An error occurred updating AIO feed {feed} to {value}")
                self.logger.exception(e)

    def receive_aio(self, feed: str, default_value=None):
        """
        Helper method to get values from aio
        :param feed: Name of feed
        :param default_value: Default value to return if nothing
        :return:
        """
        return_val = default_value
        if self._aio:
            try:
                self.logger.debug(f"Getting AIO feed {feed} value")
                response = self._aio.receive(feed=feed)
                self.logger.debug(f"AIO Feed {feed} has a value of {response.value}")
                return response.value
            except Exception as e:
                self.logger.warning(f"An error occurred getting AIO feed {feed} value")
                self.logger.exception(e)
        return return_val

    def reset_counts(self, stats: EtsyStats) -> None:
        """
        Reset stats and counters to 0

        :param stats: copy of Etsy stats to reset process
        :return:
        """
        # We need to reset the change values to 0 and publish
        self.favorites_change = 0
        self.rating_change = 0.0
        self.ratings_change = 0
        self.sales_change = 0
        self.send_aio(feed=self.get_feed_name("favorites-change"), value=self.favorites_change)
        self.send_aio(feed=self.get_feed_name("rating-change"), value=self.rating_change)
        self.send_aio(feed=self.get_feed_name("ratings-change"), value=self.ratings_change)
        self.send_aio(feed=self.get_feed_name("sales-change"), value=self.sales_change)

        # We need to get a new reset date and set the values for the starting values
        self.reset_datetime = datetime.combine(date.today(), time(hour=self.reset_hour))
        if self.reset_datetime < datetime.now():
            # Just incase you start this app after the current day's reset timer hit
            self.reset_datetime = self.reset_datetime + timedelta(days=1)
        self.logger.info(f"Counts are reset to 0. Next reset will occur at {self.reset_datetime}")
        self.favorites_start = stats.favorites
        self.rating_start = stats.rating
        self.ratings_start = stats.ratings
        self.sales_start = stats.sales
        self.send_reset_info()  # Send it when it is updated on the class instance

    def send_reset_info(self) -> None:
        """Sends reset info as dict/json. This is loaded if the script restarts so things aren't 0 if between resets"""
        self.send_aio(feed=self.get_feed_name("reset-info"), value={
            "favorites-start": self.favorites_start,
            "rating-start": self.rating_start,
            "ratings-start": self.ratings_start,
            "sales-start": self.sales_start,
            "reset-timestamp": self.reset_datetime.timestamp()
        })

    def scrape_etsy_stats(self) -> EtsyStats:
        """Used to scrape the Etsy store page. Will need to be modified if they change the way the site layout is"""
        self.logger.debug(f"Scraping {self.url}")

        favorites = None
        rating = None
        ratings = None
        sales = None
        errors = 0

        try:
            response = self._session.get(url=self.url)
            response.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Could not get url: {self.url}")
            self.logger.exception(e)
            return EtsyStats(errors=1)

        soup = BeautifulSoup(response.text, "html.parser")

        # region favorites
        try:
            scripts = soup.find_all(name="script")
            for script in scripts:
                match = re.search(r".*\"num_favorers\":(\d+),.*", script.get_text().strip())
                if match:
                    favorites = int(match[1])
        except Exception as e:
            self.logger.warning("Error occurred parsing for Favorites")
            self.logger.exception(e)
            errors += 1
        # endregion

        # region rating
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

        # region ratings
        if found_rating:
            try:
                found_ratings = found_rating.parent.parent.find(string=re.compile(r"\(\d+\)"))
                if found_ratings:
                    ratings = int(found_ratings.strip().replace("(", "").replace(")", ""))
            except Exception as e:
                self.logger.warning("Error occurred parsing for Ratings")
                self.logger.exception(e)
                errors += 1
        # endregion

        # region sales
        try:
            found_sales = soup.find(string=re.compile("([0-9,]) Sales"))
            if found_sales:
                sales = int(found_sales.get_text().strip().replace(" Sales", "").replace(",", ""))
        except Exception as e:
            self.logger.warning("Error occurred parsing for Sales")
            self.logger.exception(e)
            errors += 1
        # endregion

        return EtsyStats(favorites=favorites, rating=rating, ratings=ratings, sales=sales, errors=errors)

    def collect_and_publish(self) -> None:
        """Handles the main portion of this class and runs the helper functions in the main order"""
        self.update_total += 1
        self.logger.info(f"Checking {self.shop} for updates. Count: {self.update_total}")
        self.send_aio(feed=self.get_feed_name("update-total"), value=self.update_total)

        # Every time you run, check the reset hour to see if it changed
        self.validate_reset_hour()

        # Get Etsy stats
        stats = self.scrape_etsy_stats()
        if stats.errors > 0:
            self.send_aio(feed=self.get_feed_name("error-count"), value=stats.errors)

        # If we passed reset_datetime, process the reset using the current stats
        if datetime.now() > self.reset_datetime:
            self.reset_counts(stats=stats)

        if stats.favorites:
            favorites_change = stats.favorites - self.favorites_start
            if favorites_change != self.favorites_change:
                self.logger.info(f"A new favorite was found {self.favorites_change} -> {favorites_change}")
                self.favorites_change = favorites_change
                self.send_aio(feed=self.get_feed_name("favorites-change"), value=self.favorites_change)

        if stats.rating:
            rating_change = stats.rating - self.rating_start
            if rating_change != self.rating_change:
                message = f"Your rating changed {self.rating_change} -> {rating_change}"
                if rating_change > 0:
                    self.logger.info(message)
                else:
                    # Give warning if the rating goes down
                    self.logger.warning(message)
                self.rating_change = rating_change
                self.send_aio(feed=self.get_feed_name("rating-change"), value=self.rating_change)

        if stats.ratings:
            ratings_change = stats.ratings - self.ratings_start
            if ratings_change != self.ratings_change:
                self.logger.info(f"Your ratings changed {self.ratings_change} -> {ratings_change}")
                self.ratings_change = ratings_change
                self.send_aio(feed=self.get_feed_name("ratings-change"), value=self.ratings_change)

        if stats.sales:
            sales_change = stats.sales - self.sales_start
            if sales_change != self.sales_change:
                self.logger.info(f"Your sales changed {self.sales_change} -> {sales_change}")
                self.sales_change = sales_change
                self.send_aio(feed=self.get_feed_name("sales-change"), value=self.sales_change)


if __name__ == "__main__":
    logging.basicConfig()

    client = EstyStoreStats(shop=environ.get("ETSY_STORE_NAME"),
                            aio_username=environ.get("AIO_USERNAME"),
                            aio_password=environ.get("AIO_PASSWORD"))

    # Repeat to update the Etsy counts
    schedule.every(7).minutes.do(client.collect_and_publish)
    while True:
        schedule.run_pending()
        sleep((random()*60))
