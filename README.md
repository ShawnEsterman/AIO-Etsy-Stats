# AIO Etsy Stats

Python script to scrape an Etsy store page and publish stats to Adafruit IO. It will also keep track of stats from the start of the day so you
can use the metrics to easily see how many orders, sold items, favorites gained, or track your rating. 

---
> Cha Ching

— Nicole, the inspiration

> [!IMPORTANT]
> This python repository is a part of a late Christmas gift and now birthday present to my wife, Nicole, who started her Etsy store in 2024. I hope that she loves it! ❤️

Her store picked up traction this summer and she has been excited seeing how many Etsy she makes orders in a day. She is usually happy to get 
6-8 orders in a day. While she was away on a work trip I was on order filling duty and she would text me "Cha Ching" when she got a order that I 
needed to pack. I thought it was cute that she said "Cha Ching"[^1] and those 8 characters made me think... It would be cool if I could illuminate 
1 of each of those letters for each order she got in a day. Since 8 would be a good day.

I intend to run this project in a [docker container](docker-compose.yml) and have it update AIO every 15 minutes. In two separate efforts I plan to 
create an Neon-like LED display sign that I designed in Autodesk Fusion and run by a Pimoroni Plasma 2350 W microcontroller running CircuitPython. 
I had to [write the firmware](https://github.com/adafruit/circuitpython/pull/9923) for the board. Adafruit's CircuitPython seemed easier that MicroPython 
as they have a library for Adafruit IO using MQTT. I'll try and share that code in a separate repo and post pictures of the display when it is finished.

## Requirements

**Script Runner** - I'm running this in a docker container in a stack managed by Portainer, but anywhere you can continually run the script will work. You could create a stack in
Portainer like I am and point to this repo, set environment variables for your needs, and deploy. However, you will need to at least request a free Business Edition license as the 
option `Local filesystem path` needs to be used as it references other files from the repository.  

## Optional

If you don't want to use AIO, you can just watch the logs, but it is not as fun.

**Adafruit IO Account** - You can use a free one if you've never used it. It only makes 10 feeds which is what you get with a free account. However, on
the free account there is rate limiting so try to limit the amount of times you scrape as that function will update feeds. The code does not account for
throttling. Please don't abuse this great, free service.

**Discord Webhook** - You can add a discord webhook and have it log INFO and above messages to a Discord channel for monitoring and alerting.

## Installation

Since this is a really niche project, I am not going to publish the python code to pip or build a docker container. Please fork and download the code to
suit your needs. 

```bash
git pull https://github.com/ShawnEsterman/AIO-Etsy-Stats
cd AIO-Etsy-Stats
# Set some environment variables or a .env file. See "docker-compose.yml" or "aio-etsy-stats/main.py"
docker-compose up -d
```

[^1]: When I told Nicole I thought it was cute, she told me that Etsy puts "Cha Ching" in their emails. So it was Etsy being cute and not something she came up with 🤣
