import sys
from bs4 import BeautifulSoup
import pafy

if sys.version_info[0] < 3:
    from urllib import quote
    from urllib2 import urlopen
else:
    from urllib.request import urlopen
    from urllib.parse import quote

# disable webscrapping logs
import logging

logging.getLogger("chardet.charsetprober").setLevel(logging.WARNING)

from mycroft.skills.core import intent_handler, IntentBuilder, \
    intent_file_handler
from mycroft_jarbas_utils.skills.audio import AudioSkill

from os import listdir
import csv
import json
from os.path import join, dirname, exists
from mycroft.util.parse import fuzzy_match
import random

__author__ = 'jarbas'


class YoutubeSkill(AudioSkill):
    def __init__(self):
        self.named_urls = {}
        self.backend_preference = ["chromecast", "mopidy", "mpv", "vlc",
                                   "mplayer"]
        super(YoutubeSkill, self).__init__()
        self.add_filter("music")

        self.get_playlists_from_file()
        self.settings.set_changed_callback(self.get_playlists_from_file)

    def create_settings_meta(self):
        if "named_urls" not in self.settings:
            self.settings["named_urls"] = join(dirname(__file__),
                                               "named_urls")
        meta = {
            "name": "Youtube Skill",
            "skillMetadata": {
                "sections": [
                    {
                        "name": "Audio Configuration",
                        "fields": [
                            {
                                "type": "text",
                                "name": "default_backend",
                                "value": "vlc",
                                "label": "default_backend"
                            }
                        ]
                    },
                    {
                        "name": "Playlist Configuration",
                        "fields": [
                            {
                                "type": "label",
                                "label": "the files in this directory will be read to create aliases and playlists in this skill, the files must end in '.value' and be valid csv, with content ' song name, youtube url ', 'play filename' will play any of the links inside, 'play song name' will play that song name "
                            },
                            {
                                "type": "text",
                                "name": "named_urls",
                                "value": self.settings["named_urls"],
                                "label": "named_urls"
                            }
                        ]
                    }
                ]
            }
        }
        settings_path = join(self._dir, "settingsmeta.json")
        if not exists(settings_path):
            with open(settings_path, "w") as f:
                f.write(json.dumps(meta))

    def translate_named_urls(self, name, delim=None):
        delim = delim or ','
        result = {}
        if not name.endswith(".value"):
            name += ".value"

        try:
            with open(join(self.settings["named_urls"], name)) as f:
                reader = csv.reader(f, delimiter=delim)
                for row in reader:
                    # skip blank or comment lines
                    if not row or row[0].startswith("#"):
                        continue
                    if len(row) != 2:
                        continue
                    row[0] = row[0].rstrip().lstrip()
                    row[1] = row[1].rstrip().lstrip()
                    if row[0] not in result.keys():
                        result[row[0]] = []
                    result[row[0]].append(row[1])
            return result
        except Exception as e:
            self.log.error(str(e))
            return {}

    def get_playlists_from_file(self):
        self.named_urls = {}  # reset in case pahts changed
        # read configured url aliases
        names = listdir(self.settings["named_urls"])
        for name in names:
            name = name.replace(".value", "")
            if name not in self.named_urls:
                self.named_urls[name] = []
            style_stations = self.translate_named_urls(name)
            for station_name in style_stations:
                if station_name not in self.named_urls:
                    self.named_urls[station_name] = style_stations[station_name]
                else:
                    self.named_urls[station_name] += style_stations[station_name]
                self.named_urls[name] += style_stations[station_name]
        self.log.debug("named urls: " + str(self.named_urls))
        self.build_vocabs()

    def initialize(self):
        self.build_vocabs()

    def build_vocabs(self):
        try:
            for named_url in self.named_urls:
                self.register_vocabulary(named_url, "named_url")
        except:
            pass # no emitter, on skill load this happens

    @intent_handler(IntentBuilder("YoutubeNamedUrlPlay").optionally(
        "youtube").require("play").require("named_url").optionally("music"))
    def handle_named_play(self, message):
        named_url = message.data.get("named_url")
        urls = self.named_urls[named_url]
        random.shuffle(urls)
        # TODO use dialog file
        self.speak(named_url)
        self.youtube_play(videos=urls)

    @intent_handler(IntentBuilder("YoutubePlay").require(
        "youtube").require("play"))
    def handle_play_song_intent(self, message):
        # use adapt if youtube is included in the utterance
        # use the utterance remainder as query
        title = message.utterance_remainder()
        self.youtube_play(title)

    @intent_file_handler("youtube.intent")
    def handle_play_song_padatious_intent(self, message):
        # handle a more generic play command and extract name with padatious
        title = message.data.get("music")
        # fuzzy match with playlists
        best_score = 0
        best_name = ""
        for name in self.named_urls:
            score = fuzzy_match(title, name)
            if score > best_score:
                best_score = score
                best_name = name
        if best_score > 0.6:
            # we have a named list that matches
            urls = self.named_urls[best_name]
            random.shuffle(urls)
            # TODO use dialog
            self.speak(best_name)
            self.youtube_play(videos=urls)
        else:
            self.youtube_play(title)

    def youtube_search(self, title):
        videos = []
        self.log.info("Searching youtube for " + title)
        for v in self.search(title):
            if "channel" not in v and "list" not in v and "user" not in v \
                    and "googleads" not in v:
                videos.append(v)
        self.log.info("Youtube Videos:" + str(videos))
        return videos

    def youtube_play(self, title=None, videos=None):
        # were video links provided ?
        videos = videos or []
        if isinstance(videos, basestring):
            videos = [videos]
        # was a search requested ?
        if title is not None:
            self.speak_dialog("searching.youtube", {"music": title})
            videos = self.youtube_search(title)
        # do we have vids to play ?
        if len(videos):
            self.play(self.get_real_url(videos[0]))
            for video in videos[1:]:
                self.audio.queue(self.get_real_url(video))
        else:
            raise AssertionError("no youtube video urls to play")

    def get_real_url(self, video):
        try:
            myvid = pafy.new(video)
            stream = myvid.getbestaudio()
            return stream.url
        except Exception as e:
            self.log.error(e)

    def search(self, text):
        query = quote(text)
        url = "https://www.youtube.com/results?search_query=" + query
        response = urlopen(url)
        html = response.read()
        soup = BeautifulSoup(html, "lxml")
        vid = soup.findAll(attrs={'class': 'yt-uix-tile-link'})
        videos = []
        if vid:
            for video in vid:
                videos.append(video['href'].replace("/watch?v=", ""))
        return videos


def create_skill():
    return YoutubeSkill()
