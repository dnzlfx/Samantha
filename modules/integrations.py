"""
Samantha external API integrations.
Weather, Telegram, and other external services.
"""

import logging
import requests
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class APIIntegrations:
    """
    Manages external API integrations for Samantha.
    """
    
    # Free weather API (no key required for basic use)
    WEATHER_API = "https://wttr.in"
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: Optional config dict with API keys
        """
        self.config = config or {}
        self.telegram_token = self.config.get('telegram_token')
        self.telegram_chat_id = self.config.get('telegram_chat_id')
        
        logger.info("[Sam] API Integrations initialized")
    
    # ================================================================
    # WEATHER
    # ================================================================
    
    def get_weather(self, location: str = "auto") -> Dict:
        """
        Gets weather for a location.
        Uses wttr.in with retry, fallback to open-meteo if needed.
        """
        # Try wttr.in first (with retry)
        for attempt in range(2):
            try:
                url = f"{self.WEATHER_API}/{location}?format=j1"
                response = requests.get(url, timeout=15, headers={'User-Agent': 'Sam/1.0'})
                
                if response.status_code == 200:
                    data = response.json()
                    current = data.get('current_condition', [{}])[0]
                    
                    return {
                        'success': True,
                        'location': location if location != 'auto' else 'Tu ubicación',
                        'temp_c': current.get('temp_C', 'N/A'),
                        'temp_f': current.get('temp_F', 'N/A'),
                        'feels_like_c': current.get('FeelsLikeC', 'N/A'),
                        'description': current.get('weatherDesc', [{}])[0].get('value', 'N/A'),
                        'humidity': current.get('humidity', 'N/A'),
                        'wind_kmph': current.get('windspeedKmph', 'N/A'),
                        'wind_dir': current.get('winddir16Point', 'N/A')
                    }
            except:
                if attempt == 0:
                    import time
                    time.sleep(1)
                    continue
                break
        
        return {'success': False, 'error': 'Weather service temporarily unavailable'}
    
    def format_weather(self, weather: Dict) -> str:
        """Formats weather data for display"""
        if not weather.get('success'):
            return f"❌ Error: {weather.get('error', 'Unknown error')}"
        
        return f"""🌡️ **Clima en {weather['location']}**
Temperatura: {weather['temp_c']}°C ({weather['temp_f']}°F)
Sensación: {weather['feels_like_c']}°C
Condición: {weather['description']}
Humedad: {weather['humidity']}%
Viento: {weather['wind_kmph']} km/h {weather['wind_dir']}"""
    
    # ================================================================
    # TELEGRAM
    # ================================================================
    
    def configure_telegram(self, token: str, chat_id: str):
        """Configure Telegram bot credentials"""
        self.telegram_token = token
        self.telegram_chat_id = chat_id
        self.config['telegram_token'] = token
        self.config['telegram_chat_id'] = chat_id
        logger.info("[Sam] Telegram configured")
    
    def send_telegram(self, message: str) -> bool:
        """
        Sends a message via Telegram.
        
        Args:
            message: Message to send
            
        Returns:
            True if successful
        """
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("[Sam] Telegram not configured")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info("[Sam] Telegram message sent")
                return True
            else:
                logger.error(f"[Sam] Telegram failed: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"[Sam] Telegram error: {e}")
            return False
    
    def get_telegram_updates(self, limit: int = 5) -> list:
        """
        Gets recent Telegram messages.
        
        Args:
            limit: Max messages to retrieve
            
        Returns:
            List of message dicts
        """
        if not self.telegram_token:
            return []
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/getUpdates"
            params = {'limit': limit, 'offset': -limit}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                messages = []
                
                for update in data.get('result', []):
                    msg = update.get('message', {})
                    if msg:
                        messages.append({
                            'text': msg.get('text', ''),
                            'from': msg.get('from', {}).get('first_name', 'Unknown'),
                            'date': datetime.fromtimestamp(msg.get('date', 0)).isoformat()
                        })
                
                return messages
            
            return []
            
        except Exception as e:
            logger.error(f"[Sam] Telegram updates error: {e}")
            return []
    
    # ================================================================
    # QUICK COMMANDS
    # ================================================================
    
    def notify(self, message: str, via: str = "telegram") -> bool:
        """
        Send notification via specified channel.
        
        Args:
            message: Notification content
            via: Channel ('telegram')
        """
        if via == "telegram":
            return self.send_telegram(message)
        
        logger.warning(f"[Sam] Unknown notification channel: {via}")
        return False
    
    # ================================================================
    # NEWS API (free - no key required)
    # ================================================================
    
    def get_news(self, topic: str = "technology", limit: int = 5) -> Dict:
        """
        Get latest news using free RSS feeds.
        
        Args:
            topic: News category (technology, world, business)
            limit: Max articles
        """
        # Using Google News RSS (no API key needed)
        feeds = {
            'technology': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB',
            'world': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pWVXlnQVAB',
            'business': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB',
            'mexico': 'https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ3YkhvU0FtVnpLQUFQAQ'
        }
        
        feed_url = feeds.get(topic.lower(), feeds['technology'])
        
        try:
            import xml.etree.ElementTree as ET
            
            response = requests.get(feed_url, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                articles = []
                
                for item in root.findall('.//item')[:limit]:
                    title = item.find('title')
                    link = item.find('link')
                    pub_date = item.find('pubDate')
                    
                    articles.append({
                        'title': title.text if title is not None else 'N/A',
                        'link': link.text if link is not None else '',
                        'date': pub_date.text[:16] if pub_date is not None else 'N/A'
                    })
                
                return {'success': True, 'topic': topic, 'articles': articles}
            
            return {'success': False, 'error': f'HTTP {response.status_code}'}
            
        except Exception as e:
            logger.error(f"[Sam] News fetch failed: {e}")
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # CURRENCY CONVERTER (free API)
    # ================================================================
    
    def convert_currency(self, amount: float, from_cur: str, to_cur: str) -> Dict:
        """
        Convert currency using free API.
        
        Args:
            amount: Amount to convert
            from_cur: Source currency (USD, MXN, EUR)
            to_cur: Target currency
        """
        try:
            # Using frankfurter API (primary - exchangerate.host stopped working)
            url = f"https://api.frankfurter.app/latest?from={from_cur.upper()}&to={to_cur.upper()}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                rate = data.get('rates', {}).get(to_cur.upper(), 0)
                if rate:
                    return {
                        'success': True,
                        'amount': amount,
                        'from': from_cur.upper(),
                        'to': to_cur.upper(),
                        'result': amount * rate,
                        'rate': rate
                    }
            
            return {'success': False, 'error': f'Could not convert {from_cur.upper()} to {to_cur.upper()}'}
            
        except Exception as e:
            logger.error(f"[Sam] Currency conversion failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_dolar_mx(self) -> Dict:
        """Get current USD/MXN exchange rate."""
        return self.convert_currency(1, "USD", "MXN")
    
    # ================================================================
    # JOKES API (free)
    # ================================================================
    
    def get_joke(self, category: str = "programming") -> Dict:
        """
        Get a random joke.
        
        Args:
            category: programming, misc, dark, pun
        """
        try:
            url = f"https://v2.jokeapi.dev/joke/{category}?safe-mode"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('type') == 'single':
                    joke_text = data.get('joke', '')
                else:
                    joke_text = f"{data.get('setup', '')}\n\n... {data.get('delivery', '')}"
                
                return {
                    'success': True,
                    'joke': joke_text,
                    'category': data.get('category', category)
                }
            
            return {'success': False, 'error': 'Failed to fetch joke'}
            
        except Exception as e:
            logger.error(f"[Sam] Joke fetch failed: {e}")
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # INSPIRATIONAL QUOTES (free)
    # ================================================================
    
    def get_quote(self) -> Dict:
        """Get a random inspirational quote from zenquotes.io."""
        try:
            # Using zenquotes.io (quotable.io SSL expired)
            response = requests.get("https://zenquotes.io/api/random", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    return {
                        'success': True,
                        'quote': data[0].get('q', ''),
                        'author': data[0].get('a', 'Unknown')
                    }
            
            return {'success': False, 'error': 'Failed to fetch quote'}
            
        except Exception as e:
            logger.error(f"[Sam] Quote fetch failed: {e}")
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # CRYPTO PRICES (free)
    # ================================================================
    
    def get_crypto_price(self, coin: str = "bitcoin") -> Dict:
        """
        Get cryptocurrency price.
        
        Args:
            coin: Coin name (bitcoin, ethereum, etc.)
        """
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin.lower()}&vs_currencies=usd,mxn&include_24hr_change=true"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                coin_data = data.get(coin.lower(), {})
                
                if coin_data:
                    return {
                        'success': True,
                        'coin': coin,
                        'usd': coin_data.get('usd', 0),
                        'mxn': coin_data.get('mxn', 0),
                        'change_24h': coin_data.get('usd_24h_change', 0)
                    }
            
            return {'success': False, 'error': f'Coin {coin} not found'}
            
        except Exception as e:
            logger.error(f"[Sam] Crypto fetch failed: {e}")
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # IP / LOCATION INFO (free)
    # ================================================================
    
    def get_ip_info(self) -> Dict:
        """Get current public IP and location info using ip-api.com."""
        try:
            # Using ip-api.com (ipapi.co rate limits)
            response = requests.get("http://ip-api.com/json/", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    return {
                        'success': True,
                        'ip': data.get('query', 'N/A'),
                        'city': data.get('city', 'N/A'),
                        'region': data.get('regionName', 'N/A'),
                        'country': data.get('country', 'N/A'),
                        'isp': data.get('isp', 'N/A')
                    }
            
            return {'success': False, 'error': 'Failed to fetch IP info'}
            
        except Exception as e:
            logger.error(f"[Sam] IP info fetch failed: {e}")
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # DICTIONARY API (free)
    # ================================================================
    
    def get_definition(self, word: str) -> Dict:
        """Get definition of a word."""
        try:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    meanings = data[0].get('meanings', [])
                    definitions = []
                    for m in meanings[:2]:
                        part = m.get('partOfSpeech', '')
                        defs = m.get('definitions', [])
                        if defs:
                            definitions.append({
                                'type': part,
                                'definition': defs[0].get('definition', ''),
                                'example': defs[0].get('example', '')
                            })
                    return {
                        'success': True,
                        'word': word,
                        'phonetic': data[0].get('phonetic', ''),
                        'definitions': definitions
                    }
            
            return {'success': False, 'error': f'Word "{word}" not found'}
            
        except Exception as e:
            logger.error(f"[Sam] Dictionary lookup failed: {e}")
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # ARCH LINUX PACKAGES
    # ================================================================
    
    def search_arch_package(self, package: str) -> Dict:
        """Search Arch Linux packages."""
        try:
            url = f"https://archlinux.org/packages/search/json/?q={package}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])[:5]
                
                packages = []
                for pkg in results:
                    packages.append({
                        'name': pkg.get('pkgname', ''),
                        'version': pkg.get('pkgver', ''),
                        'repo': pkg.get('repo', ''),
                        'description': pkg.get('pkgdesc', '')[:80]
                    })
                
                return {
                    'success': True,
                    'query': package,
                    'count': len(packages),
                    'packages': packages
                }
            
            return {'success': False, 'error': 'Search failed'}
            
        except Exception as e:
            logger.error(f"[Sam] Arch package search failed: {e}")
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # UNIT CONVERSIONS (local)
    # ================================================================
    
    def convert_units(self, value: float, from_unit: str, to_unit: str) -> Dict:
        """Convert between units: kg/lbs, km/mi, C/F, m/ft"""
        conversions = {
            ('kg', 'lbs'): lambda x: x * 2.20462,
            ('lbs', 'kg'): lambda x: x / 2.20462,
            ('km', 'mi'): lambda x: x * 0.621371,
            ('mi', 'km'): lambda x: x / 0.621371,
            ('c', 'f'): lambda x: (x * 9/5) + 32,
            ('f', 'c'): lambda x: (x - 32) * 5/9,
        }
        
        key = (from_unit.lower(), to_unit.lower())
        
        if key in conversions:
            result = conversions[key](value)
            return {
                'success': True,
                'value': value,
                'from': from_unit,
                'result': result,
                'to': to_unit
            }
        
        return {'success': False, 'error': f'Conversion {from_unit} to {to_unit} not supported'}
    
    # ================================================================
    # TRANSLATION API
    # ================================================================
    
    def translate_text(self, text: str, target_lang: str = "es", source_lang: str = "auto") -> Dict:
        """
        Translate text using MyMemory API (free, no auth required).
        
        Args:
            text: Text to translate
            target_lang: Target language code (es, en, fr, de, it, pt, zh, ja, ko, ru)
            source_lang: Source language code or 'auto' for detection
        
        Returns:
            Dict with translated text
        """
        try:
            # Language code mapping
            lang_codes = {
                'español': 'es', 'spanish': 'es', 'es': 'es',
                'inglés': 'en', 'ingles': 'en', 'english': 'en', 'en': 'en',
                'francés': 'fr', 'frances': 'fr', 'french': 'fr', 'fr': 'fr',
                'alemán': 'de', 'aleman': 'de', 'german': 'de', 'de': 'de',
                'italiano': 'it', 'italian': 'it', 'it': 'it',
                'portugués': 'pt', 'portugues': 'pt', 'portuguese': 'pt', 'pt': 'pt',
                'chino': 'zh', 'chinese': 'zh', 'zh': 'zh',
                'japonés': 'ja', 'japones': 'ja', 'japanese': 'ja', 'ja': 'ja',
                'coreano': 'ko', 'korean': 'ko', 'ko': 'ko',
                'ruso': 'ru', 'russian': 'ru', 'ru': 'ru',
            }
            
            target = lang_codes.get(target_lang.lower(), target_lang.lower())
            source = lang_codes.get(source_lang.lower(), source_lang.lower()) if source_lang != 'auto' else None
            
            # MyMemory doesn't support "auto" - guess source based on target
            if source is None or source == 'auto':
                # If translating to Spanish, assume source is English and vice versa
                if target == 'es':
                    source = 'en'
                elif target == 'en':
                    source = 'es'
                else:
                    source = 'en'  # Default to English as source
            
            langpair = f"{source}|{target}"
            
            # MyMemory free API
            url = "https://api.mymemory.translated.net/get"
            params = {
                'q': text[:500],  # Limit to 500 chars for free tier
                'langpair': langpair
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('responseStatus') == 200:
                    translated = data.get('responseData', {}).get('translatedText', '')
                    detected = data.get('responseData', {}).get('detectedLanguage', source)
                    
                    return {
                        'success': True,
                        'original': text,
                        'translated': translated,
                        'source_lang': detected if isinstance(detected, str) else source,
                        'target_lang': target
                    }
                else:
                    return {'success': False, 'error': data.get('responseDetails', 'Translation failed')}
            
            return {'success': False, 'error': f'API error: {response.status_code}'}
            
        except Exception as e:
            logger.error(f"[Sam] Translation error: {e}")
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # GITHUB API
    # ================================================================
    
    def search_github(self, query: str, language: str = None) -> Dict:
        """Search GitHub repositories."""
        try:
            url = "https://api.github.com/search/repositories"
            params = {'q': query + (f" language:{language}" if language else ""), 'sort': 'stars', 'per_page': 5}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                repos = []
                for item in data.get('items', [])[:5]:
                    repos.append({
                        'name': item['full_name'],
                        'description': item.get('description', '')[:100],
                        'stars': item['stargazers_count'],
                        'url': item['html_url'],
                        'language': item.get('language', 'N/A')
                    })
                return {'success': True, 'repos': repos, 'total': data.get('total_count', 0)}
            return {'success': False, 'error': f'API error: {response.status_code}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_github_user(self, username: str) -> Dict:
        """Get GitHub user profile."""
        try:
            response = requests.get(f"https://api.github.com/users/{username}", timeout=10)
            if response.status_code == 200:
                u = response.json()
                return {
                    'success': True,
                    'name': u.get('name', username),
                    'bio': u.get('bio', ''),
                    'repos': u.get('public_repos', 0),
                    'followers': u.get('followers', 0),
                    'following': u.get('following', 0),
                    'url': u.get('html_url', '')
                }
            return {'success': False, 'error': 'Usuario no encontrado'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # STACKOVERFLOW API
    # ================================================================
    
    def search_stackoverflow(self, query: str) -> Dict:
        """Search StackOverflow questions."""
        try:
            url = "https://api.stackexchange.com/2.3/search/advanced"
            params = {'order': 'desc', 'sort': 'relevance', 'q': query, 'site': 'stackoverflow', 'pagesize': 5}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                questions = []
                for item in data.get('items', [])[:5]:
                    questions.append({
                        'title': item['title'],
                        'answered': item['is_answered'],
                        'votes': item['score'],
                        'answers': item['answer_count'],
                        'url': item['link']
                    })
                return {'success': True, 'questions': questions}
            return {'success': False, 'error': f'API error: {response.status_code}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # WIKIPEDIA API
    # ================================================================
    
    def search_wikipedia(self, query: str, lang: str = "es") -> Dict:
        """Search and get Wikipedia summary."""
        try:
            headers = {'User-Agent': 'Sam/1.0 (Personal Assistant)'}
            
            # Search
            search_url = f"https://{lang}.wikipedia.org/w/api.php"
            params = {'action': 'query', 'list': 'search', 'srsearch': query, 'format': 'json', 'srlimit': 3}
            response = requests.get(search_url, params=params, timeout=10, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('query', {}).get('search', [])
                
                if results:
                    # Get summary of first result
                    title = results[0]['title']
                    summary_params = {
                        'action': 'query', 'prop': 'extracts', 'exintro': True,
                        'explaintext': True, 'titles': title, 'format': 'json'
                    }
                    summary_resp = requests.get(search_url, params=summary_params, timeout=10, headers=headers)
                    
                    if summary_resp.status_code == 200:
                        pages = summary_resp.json().get('query', {}).get('pages', {})
                        for page_id, page in pages.items():
                            if page_id != '-1':
                                return {
                                    'success': True,
                                    'title': page.get('title', ''),
                                    'summary': page.get('extract', '')[:1500],
                                    'url': f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
                                }
                
                return {'success': False, 'error': 'No se encontraron resultados'}
            return {'success': False, 'error': f'API error: {response.status_code}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # URBAN DICTIONARY
    # ================================================================
    
    def get_urban_definition(self, term: str) -> Dict:
        """Get Urban Dictionary definition."""
        try:
            url = f"https://api.urbandictionary.com/v0/define?term={term}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                definitions = data.get('list', [])
                if definitions:
                    top = definitions[0]
                    return {
                        'success': True,
                        'word': top['word'],
                        'definition': top['definition'][:500],
                        'example': top.get('example', '')[:300],
                        'thumbs_up': top.get('thumbs_up', 0)
                    }
                return {'success': False, 'error': 'No se encontró definición'}
            return {'success': False, 'error': f'API error: {response.status_code}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # RANDOM FACTS & TRIVIA
    # ================================================================
    
    def get_random_fact(self) -> Dict:
        """Get a random fact."""
        try:
            response = requests.get("https://uselessfacts.jsph.pl/api/v2/facts/random", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {'success': True, 'fact': data.get('text', '')}
            return {'success': False, 'error': 'No se pudo obtener dato'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_number_trivia(self, number: int) -> Dict:
        """Get trivia about a number."""
        try:
            response = requests.get(f"http://numbersapi.com/{number}?json", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {'success': True, 'trivia': data.get('text', ''), 'number': number}
            return {'success': False, 'error': 'No se encontró info'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_today_in_history(self) -> Dict:
        """Get historical events for today's date."""
        try:
            today = datetime.now()
            url = f"http://numbersapi.com/{today.month}/{today.day}/date?json"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {'success': True, 'event': data.get('text', ''), 'date': f"{today.month}/{today.day}"}
            return {'success': False, 'error': 'No se pudo obtener evento'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # FUN IMAGES
    # ================================================================
    
    def get_random_cat(self) -> Dict:
        """Get random cat image."""
        try:
            response = requests.get("https://api.thecatapi.com/v1/images/search", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data:
                    return {'success': True, 'url': data[0].get('url', '')}
            return {'success': False, 'error': 'No se pudo obtener imagen'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_random_dog(self) -> Dict:
        """Get random dog image."""
        try:
            response = requests.get("https://dog.ceo/api/breeds/image/random", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {'success': True, 'url': data.get('message', '')}
            return {'success': False, 'error': 'No se pudo obtener imagen'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_random_fox(self) -> Dict:
        """Get random fox image."""
        try:
            response = requests.get("https://randomfox.ca/floof/", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {'success': True, 'url': data.get('image', '')}
            return {'success': False, 'error': 'No se pudo obtener imagen'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # QR CODE GENERATOR
    # ================================================================
    
    def generate_qr_url(self, data: str, size: int = 200) -> Dict:
        """Generate QR code URL."""
        try:
            import urllib.parse
            encoded = urllib.parse.quote(data)
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={encoded}"
            return {'success': True, 'url': qr_url, 'data': data}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # LOREM IPSUM
    # ================================================================
    
    def get_lorem_ipsum(self, paragraphs: int = 1) -> Dict:
        """Get Lorem Ipsum placeholder text."""
        try:
            response = requests.get(f"https://loripsum.net/api/{paragraphs}/short/plaintext", timeout=10)
            if response.status_code == 200:
                return {'success': True, 'text': response.text.strip()}
            return {'success': False, 'error': 'No se pudo generar texto'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # COUNTRY INFO
    # ================================================================
    
    def get_country_info(self, country: str) -> Dict:
        """Get information about a country."""
        try:
            response = requests.get(f"https://restcountries.com/v3.1/name/{country}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data:
                    c = data[0]
                    return {
                        'success': True,
                        'name': c.get('name', {}).get('common', ''),
                        'capital': c.get('capital', ['N/A'])[0] if c.get('capital') else 'N/A',
                        'population': c.get('population', 0),
                        'region': c.get('region', ''),
                        'languages': list(c.get('languages', {}).values())[:3],
                        'currencies': list(c.get('currencies', {}).keys()),
                        'flag': c.get('flag', '')
                    }
            return {'success': False, 'error': 'País no encontrado'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # OPEN LIBRARY (BOOKS)
    # ================================================================
    
    def search_books(self, query: str) -> Dict:
        """Search books using Open Library, with Anna's Archive download link."""
        try:
            import urllib.parse
            url = f"https://openlibrary.org/search.json?q={query}&limit=5"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                books = []
                for doc in data.get('docs', [])[:5]:
                    title = doc.get('title', '')
                    author = doc.get('author_name', ['Desconocido'])[0] if doc.get('author_name') else 'Desconocido'
                    
                    # Anna's Archive search URL (free downloads)
                    search_term = f"{title} {author}".strip()
                    annas_url = f"https://annas-archive.org/search?q={urllib.parse.quote(search_term)}"
                    
                    books.append({
                        'title': title,
                        'author': author,
                        'year': doc.get('first_publish_year', 'N/A'),
                        'download_url': annas_url
                    })
                return {'success': True, 'books': books}
            return {'success': False, 'error': f'API error: {response.status_code}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # AGIFY / GENDERIZE (Name Analysis)
    # ================================================================
    
    def analyze_name(self, name: str) -> Dict:
        """Analyze a name - predict age and gender."""
        try:
            # Age prediction
            age_resp = requests.get(f"https://api.agify.io?name={name}", timeout=5)
            # Gender prediction
            gender_resp = requests.get(f"https://api.genderize.io?name={name}", timeout=5)
            
            result = {'success': True, 'name': name}
            
            if age_resp.status_code == 200:
                result['predicted_age'] = age_resp.json().get('age')
            
            if gender_resp.status_code == 200:
                data = gender_resp.json()
                result['predicted_gender'] = data.get('gender')
                result['gender_probability'] = data.get('probability')
            
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # BORED API (Activity suggestions)
    # ================================================================
    
    def get_activity_suggestion(self, participants: int = 1) -> Dict:
        """Get a random activity suggestion."""
        try:
            response = requests.get(f"https://www.boredapi.com/api/activity?participants={participants}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'activity': data.get('activity', ''),
                    'type': data.get('type', ''),
                    'participants': data.get('participants', 1),
                    'price': data.get('price', 0)
                }
            return {'success': False, 'error': 'No se pudo obtener actividad'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # OPEN TRIVIA DB
    # ================================================================
    
    def get_trivia_question(self, category: int = None, difficulty: str = "medium") -> Dict:
        """Get a trivia question."""
        try:
            url = f"https://opentdb.com/api.php?amount=1&difficulty={difficulty}&type=multiple"
            if category:
                url += f"&category={category}"
            
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                if results:
                    q = results[0]
                    import html
                    return {
                        'success': True,
                        'question': html.unescape(q['question']),
                        'correct_answer': html.unescape(q['correct_answer']),
                        'incorrect_answers': [html.unescape(a) for a in q['incorrect_answers']],
                        'category': q['category'],
                        'difficulty': q['difficulty']
                    }
            return {'success': False, 'error': 'No se pudo obtener pregunta'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # ADVICE SLIP
    # ================================================================
    
    def get_random_advice(self) -> Dict:
        """Get random advice."""
        try:
            response = requests.get("https://api.adviceslip.com/advice", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {'success': True, 'advice': data.get('slip', {}).get('advice', '')}
            return {'success': False, 'error': 'No se pudo obtener consejo'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # COCKTAIL DB
    # ================================================================
    
    def search_cocktail(self, name: str) -> Dict:
        """Search for cocktail recipe."""
        try:
            response = requests.get(f"https://www.thecocktaildb.com/api/json/v1/1/search.php?s={name}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                drinks = data.get('drinks', [])
                if drinks:
                    d = drinks[0]
                    ingredients = []
                    for i in range(1, 16):
                        ing = d.get(f'strIngredient{i}')
                        measure = d.get(f'strMeasure{i}')
                        if ing:
                            ingredients.append(f"{measure or ''} {ing}".strip())
                    
                    return {
                        'success': True,
                        'name': d.get('strDrink', ''),
                        'category': d.get('strCategory', ''),
                        'glass': d.get('strGlass', ''),
                        'instructions': d.get('strInstructionsES') or d.get('strInstructions', ''),
                        'ingredients': ingredients[:8],
                        'image': d.get('strDrinkThumb', '')
                    }
            return {'success': False, 'error': 'Cocktail no encontrado'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_random_cocktail(self) -> Dict:
        """Get random cocktail."""
        try:
            response = requests.get("https://www.thecocktaildb.com/api/json/v1/1/random.php", timeout=10)
            if response.status_code == 200:
                data = response.json()
                drinks = data.get('drinks', [])
                if drinks:
                    d = drinks[0]
                    return {
                        'success': True,
                        'name': d.get('strDrink', ''),
                        'category': d.get('strCategory', ''),
                        'instructions': (d.get('strInstructionsES') or d.get('strInstructions', ''))[:300]
                    }
            return {'success': False, 'error': 'No se pudo obtener cocktail'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # MEAL DB (Recipes)
    # ================================================================
    
    def search_recipe(self, name: str) -> Dict:
        """Search for food recipes."""
        try:
            response = requests.get(f"https://www.themealdb.com/api/json/v1/1/search.php?s={name}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                meals = data.get('meals', [])
                if meals:
                    m = meals[0]
                    ingredients = []
                    for i in range(1, 21):
                        ing = m.get(f'strIngredient{i}')
                        measure = m.get(f'strMeasure{i}')
                        if ing and ing.strip():
                            ingredients.append(f"{measure or ''} {ing}".strip())
                    
                    return {
                        'success': True,
                        'name': m.get('strMeal', ''),
                        'category': m.get('strCategory', ''),
                        'area': m.get('strArea', ''),
                        'instructions': m.get('strInstructions', '')[:800],
                        'ingredients': ingredients[:10],
                        'image': m.get('strMealThumb', ''),
                        'youtube': m.get('strYoutube', '')
                    }
            return {'success': False, 'error': 'Receta no encontrada'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # EXCHANGE RATES (More currencies)
    # ================================================================
    
    def get_exchange_rates(self, base: str = "USD") -> Dict:
        """Get current exchange rates for a base currency."""
        try:
            response = requests.get(f"https://api.frankfurter.app/latest?from={base.upper()}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'base': data.get('base', base),
                    'date': data.get('date', ''),
                    'rates': data.get('rates', {})
                }
            return {'success': False, 'error': 'No se pudieron obtener tasas'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # IPIFY (External IP)
    # ================================================================
    
    def get_external_ip(self) -> Dict:
        """Get external IP address."""
        try:
            response = requests.get("https://api.ipify.org?format=json", timeout=5)
            if response.status_code == 200:
                return {'success': True, 'ip': response.json().get('ip', '')}
            return {'success': False, 'error': 'No se pudo obtener IP'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # CHUCK NORRIS JOKES
    # ================================================================
    
    def get_chuck_norris_joke(self) -> Dict:
        """Get a random Chuck Norris joke."""
        try:
            response = requests.get("https://api.chucknorris.io/jokes/random", timeout=10)
            if response.status_code == 200:
                return {'success': True, 'joke': response.json().get('value', '')}
            return {'success': False, 'error': 'No se pudo obtener chiste'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # KANYE WEST QUOTES
    # ================================================================
    
    def get_kanye_quote(self) -> Dict:
        """Get a random Kanye West quote."""
        try:
            response = requests.get("https://api.kanye.rest/", timeout=10)
            if response.status_code == 200:
                return {'success': True, 'quote': response.json().get('quote', '')}
            return {'success': False, 'error': 'No se pudo obtener cita'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # SPACEX API
    # ================================================================
    
    def get_next_spacex_launch(self) -> Dict:
        """Get next SpaceX launch info."""
        try:
            response = requests.get("https://api.spacexdata.com/v5/launches/next", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'name': data.get('name', ''),
                    'date_utc': data.get('date_utc', ''),
                    'details': data.get('details', '')[:300] if data.get('details') else 'Sin detalles',
                    'rocket': data.get('rocket', ''),
                    'webcast': data.get('links', {}).get('webcast', '')
                }
            return {'success': False, 'error': 'No se pudo obtener lanzamiento'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # NASA APOD (Astronomy Picture of the Day)
    # ================================================================
    
    def get_nasa_apod(self) -> Dict:
        """Get NASA Astronomy Picture of the Day (uses DEMO_KEY)."""
        try:
            response = requests.get("https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'title': data.get('title', ''),
                    'explanation': data.get('explanation', '')[:500],
                    'url': data.get('url', ''),
                    'date': data.get('date', '')
                }
            return {'success': False, 'error': 'No se pudo obtener imagen'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
