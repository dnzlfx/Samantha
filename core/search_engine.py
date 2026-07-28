"""
Samantha search engine.
Provides cache, context enrichment, deep scraping, and AI-driven queries.
"""

import logging
import requests
import hashlib
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import re

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


# ============================================================================
# SEARCH CACHE - Avoid redundant searches
# ============================================================================

class SearchCache:
    """Cache for web search results with TTL (15 minutes default)"""
    
    def __init__(self, ttl_minutes: int = 15):
        self.cache: Dict[str, Dict] = {}
        self.ttl = timedelta(minutes=ttl_minutes)
    
    def _get_key(self, query: str) -> str:
        """Generate cache key from query"""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()[:16]
    
    def get(self, query: str) -> Optional[Dict]:
        """Get cached result if exists and not expired"""
        key = self._get_key(query)
        if key in self.cache:
            entry = self.cache[key]
            if datetime.now() - entry['timestamp'] < self.ttl:
                logger.info(f"[Sam Cache] HIT for: {query[:50]}...")
                return entry['result']
            else:
                # Expired, remove
                del self.cache[key]
        return None
    
    def set(self, query: str, result: Dict) -> None:
        """Store result in cache"""
        key = self._get_key(query)
        self.cache[key] = {
            'result': result,
            'timestamp': datetime.now()
        }
        logger.info(f"[Sam Cache] STORED: {query[:50]}...")
    
    def has(self, query: str) -> bool:
        """Check if query is cached (and not expired)"""
        return self.get(query) is not None
    
    def clear(self) -> None:
        """Clear all cached results"""
        self.cache.clear()


# ============================================================================
# CONTEXTUAL ENRICHER - Use conversation context for better searches
# ============================================================================

class ContextualEnricher:
    """Enriches vague queries with conversation context"""
    
    VAGUE_QUERIES = [
        'mejorarlo', 'como hacerlo', 'que tan efectivo', 'mas información',
        'explicalo', 'dame ejemplos', 'como se hace', 'y eso', 'por que',
        'esto', 'eso', 'aquello'
    ]
    
    def extract_context(self, messages: List[Dict], num_exchanges: int = 3) -> str:
        """Extract context from last N exchanges for search enrichment"""
        if not messages or len(messages) <= 1:
            return ""
        
        # Get last N*2 messages (user + assistant pairs), skip system prompt
        num_msgs = num_exchanges * 2
        recent = messages[-num_msgs:] if len(messages) > num_msgs else messages[1:]
        
        context_parts = []
        for msg in recent:
            if msg['role'] == 'user':
                content = msg['content']
                # Skip messages that contain search data
                if '=== DATOS DE BÚSQUEDA' in content or '=== RESULTADOS' in content:
                    # Extract just the original query
                    lines = content.split('\n')
                    for line in lines:
                        if line.strip() and not line.startswith('===') and not line.startswith('IMPORTANTE'):
                            content = line[:100]
                            break
                else:
                    content = content[:100].replace('\n', ' ')
                context_parts.append(f"User: {content}")
            elif msg['role'] == 'assistant':
                content = msg['content'][:100].replace('\n', ' ')
                context_parts.append(f"Sam: {content}")
        
        return "\n".join(context_parts) if context_parts else ""
    
    def is_vague_query(self, query: str) -> bool:
        """Check if query is vague and needs context"""
        query_lower = query.lower()
        return any(vague in query_lower for vague in self.VAGUE_QUERIES)
    
    def enrich_query(self, query: str, messages: List[Dict]) -> Tuple[str, str]:
        """Enrich vague query with conversation context"""
        if not self.is_vague_query(query):
            return query, ""
        
        context = self.extract_context(messages)
        if not context:
            return query, ""
        
        # Find last substantive user query
        for msg in reversed(messages):
            if msg['role'] == 'user' and '===' not in msg['content']:
                keywords = msg['content'][:50].replace('\n', ' ').strip()
                
                # Build enriched query based on intent
                if 'mejorar' in query.lower():
                    enriched = f"como mejorar {keywords}"
                elif 'efectivo' in query.lower():
                    enriched = f"que tan efectivo es {keywords}"
                elif 'hacerlo' in query.lower():
                    enriched = f"como hacer {keywords}"
                else:
                    enriched = f"{keywords} {query}"
                
                logger.info(f"[Sam Enricher] '{query}' → '{enriched}'")
                return enriched, context
        
        return query, context


# ============================================================================
# QUERY OPTIMIZER - Fixed to NOT remove critical words
# ============================================================================

class QueryOptimizer:
    """Query optimizer - FIXED: Only removes truly useless filler words"""
    
    # CRITICAL FIX: Only remove actual filler words, NOT search-related terms
    SPANISH_STOPWORDS = {
        # Articles and prepositions ONLY
        'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
        'de', 'del', 'al', 'a', 'en', 'con', 'por', 'para',
        # Polite fillers
        'por', 'favor', 'porfavor', 'porfa', 'puedes', 'podrias', 'podrías',
        'me', 'te', 'se', 'nos',
        # Question starters that add no search value
        'como', 'cómo', 'cual', 'cuál', 'donde', 'dónde', 'cuando', 'cuándo',
        # Very common verbs
        'es', 'son', 'ser', 'estar', 'hay'
    }
    # NEVER REMOVE: busca, buscar, búsqueda, información, noticias, etc.
    
    def classify_query_type(self, query: str) -> str:
        query_lower = query.lower()
        if any(word in query_lower for word in ['letra', 'lyrics', 'canción', 'song']):
            return "lyrics"
        elif any(word in query_lower for word in ['noticias', 'pasó', 'ayer', 'hoy', 'noticia']):
            return "news"
        elif any(word in query_lower for word in ['precio', 'costo', 'cuanto cuesta', 'cuánto cuesta']):
            return "price"
        elif any(word in query_lower for word in ['tutorial', 'guía', 'guia', 'ejemplo', 'como hacer']):
            return "tutorial"
        return "general"
    
    def optimize(self, raw_query: str) -> Tuple[str, str]:
        """Smart query optimization - preserves meaning"""
        if not raw_query:
            return "", "general"
        
        query_lower = raw_query.lower()
        query_type = self.classify_query_type(raw_query)
        
        # LYRICS: Extract artist + song, add "lyrics" once
        if query_type == "lyrics":
            cleaned = raw_query
            for trigger in ['dame la letra de', 'letra de la canción', 'letra de', 
                          'busca la letra', 'dame', 'quiero la letra']:
                cleaned = re.sub(re.escape(trigger), '', cleaned, flags=re.IGNORECASE)
            
            cleaned = cleaned.strip().strip('"').strip("'")
            
            # Keep meaningful words, just remove basic stopwords
            parts = [w for w in cleaned.split() if w.lower() not in self.SPANISH_STOPWORDS and len(w) > 1]
            
            # Add "lyrics" ONLY if not present
            if not any(kw in query_lower for kw in ['lyrics', 'lyric']):
                parts.append('lyrics')
            
            optimized = " ".join(parts)
            logger.info(f"[Sam Optimizer] Lyrics: '{raw_query}' → '{optimized}'")
            return optimized, query_type
        
        # NEWS: Entity + date context
        if query_type == "news":
            ahora = datetime.now()
            meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
                    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
            
            if "ayer" in query_lower:
                fecha = ahora - timedelta(days=1)
            else:
                fecha = ahora
            date_str = f"{fecha.day} {meses[fecha.month-1]} {fecha.year}"
            
            # Keep proper nouns and important words
            words = []
            for w in raw_query.split():
                # Keep if: proper noun, not stopword, or important keyword
                if (w and w[0].isupper()) or w.lower() not in self.SPANISH_STOPWORDS:
                    words.append(w)
            
            if 'noticias' not in query_lower:
                words.append('noticias')
            words.append(date_str)
            
            optimized = " ".join(words)
            logger.info(f"[Sam Optimizer] News: '{raw_query}' → '{optimized}'")
            return optimized, query_type
        
        # PRICE: Translate electricity terms for Mexico
        if query_type == "price":
            ahora = datetime.now()
            meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
                    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
            
            # Translate common misspellings/variations of kilowatt
            optimized = query_lower
            electricity_terms = ['kilowatt', 'kilowat', 'kilwhat', 'kilovatio', 'kwh', 'kw']
            
            if any(term in query_lower for term in electricity_terms):
                # Replace with proper search terms for Mexico
                for term in electricity_terms:
                    optimized = optimized.replace(term, '')
                
                # Build better query
                location = ""
                if 'mexico' in query_lower or 'méxico' in query_lower:
                    location = "México "
                if 'san luis' in query_lower:
                    location = "San Luis Potosí "
                
                optimized = f"tarifa eléctrica CFE kWh {location}{meses[ahora.month-1]} {ahora.year}"
                logger.info(f"[Sam Optimizer] Price/Electricity: '{raw_query}' → '{optimized}'")
                return optimized, query_type
            
            # General price query
            optimized = f"{raw_query} precio {meses[ahora.month-1]} {ahora.year}"
            logger.info(f"[Sam Optimizer] Price: '{raw_query}' → '{optimized}'")
            return optimized, query_type
        
        # GENERAL: Minimal optimization - keep the query mostly intact
        # Only remove obvious filler words
        words = []
        for w in raw_query.split():
            w_lower = w.lower()
            # Keep word if:
            # - It's a proper noun (starts with uppercase)
            # - It's not in stopwords
            # - It's longer than 2 chars (keeps meaningful short words like "LLM")
            if (w and w[0].isupper()) or w_lower not in self.SPANISH_STOPWORDS or len(w) > 2:
                words.append(w)
        
        optimized = " ".join(words) if words else raw_query
        logger.info(f"[Sam Optimizer] General: '{raw_query}' → '{optimized}'")
        return optimized, query_type


class DeepScraper:
    """DEEP content extractor - NO SNIPPETS"""
    
    LYRICS_SITES = {
        'genius.com': {'tag': 'div', 'attrs': {'data-lyrics-container': 'true'}},
        'letras.com': {'tag': 'div', 'attrs': {'class': 'lyric-original'}},
        'musixmatch.com': {'tag': 'span', 'attrs': {'class': 'lyrics__content__ok'}},
        'azlyrics.com': {'tag': 'div', 'attrs': {'class': None}},
    }
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8'
        })
    
    def extract_content(self, url: str, content_type: str) -> Optional[Dict]:
        """Extract REAL content from URL"""
        try:
            logger.info(f"[Sam] Deep scraping: {url}")
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Lyrics-specific extraction
            if content_type == "lyrics":
                domain = next((d for d in self.LYRICS_SITES if d in url), None)
                
                # Special handling for Genius - try multiple selectors
                if 'genius.com' in url:
                    # Try multiple selectors for Genius
                    selectors_to_try = [
                        ('div', {'data-lyrics-container': 'true'}),
                        ('div', {'class': re.compile(r'Lyrics__Container')}),
                        ('div', {'class': re.compile(r'lyrics')}),
                    ]
                    
                    all_lyrics = []
                    for tag, attrs in selectors_to_try:
                        elements = soup.find_all(tag, attrs)
                        for elem in elements:
                            text = self._clean_text(elem)
                            if text and len(text) > 50:
                                all_lyrics.append(text)
                    
                    if all_lyrics:
                        full_lyrics = '\n'.join(all_lyrics)
                        logger.info(f"[Sam] Genius: Extracted {len(full_lyrics)} chars")
                        return {
                            'content': full_lyrics,
                            'url': url,
                            'source': 'genius.com',
                            'length': len(full_lyrics)
                        }
                
                # Special handling for AZLyrics
                elif 'azlyrics.com' in url:
                    # AZLyrics has lyrics in a div after <!-- Usage of azlyrics.com content -->
                    # Find all divs without class that contain substantial text
                    all_divs = soup.find_all('div', class_=False, id=False)
                    for div in all_divs:
                        text = div.get_text(strip=True)
                        # Lyrics div is usually 500+ chars and doesn't contain navigation
                        if len(text) > 500 and 'Submit Corrections' not in text and 'AZLyrics' not in text[:50]:
                            lyrics = self._clean_text(div)
                            if len(lyrics) > 300:
                                logger.info(f"[Sam] ZLyrics: Extracted {len(lyrics)} chars")
                                return {
                                    'content': lyrics,
                                    'url': url,
                                    'source': 'azlyrics.com',
                                    'length': len(lyrics)
                                }
                
                elif domain:
                    selectors = self.LYRICS_SITES[domain]
                    element = soup.find(selectors['tag'], selectors['attrs'])
                    if element:
                        text = self._clean_text(element)
                        if len(text) > 200:  # Substance validation
                            logger.info(f"[Sam] Extracted {len(text)} chars from {domain}")
                            return {
                                'content': text,
                                'url': url,
                                'source': domain,
                                'length': len(text)
                            }
            
            # Generic extraction for news/articles
            for selector in [
                ('article', {}),
                ('div', {'class': re.compile(r'content|article|post|main', re.I)}),
                ('main', {}),
            ]:
                element = soup.find(selector[0], selector[1])
                if element:
                    text = self._clean_text(element)
                    if len(text) > 500:  # Min 500 chars for substance
                        logger.info(f"[Sam] Extracted {len(text)} chars")
                        return {
                            'content': text[:3000],  # Limit to 3000 chars to prevent overwhelming LLM
                            'url': url,
                            'length': len(text)
                        }
            
            logger.warning(f"[Sam] ⚠️ No substantial content found in {url}")
            return None
            
        except Exception as e:
            logger.error(f"[Sam] Scraping error for {url}: {e}")
            return None
    
    def _clean_text(self, element) -> str:
        """Clean extracted text"""
        # Remove unwanted tags
        for tag in element(['script', 'style', 'nav', 'header', 'footer', 'aside', 'ad']):
            tag.decompose()
        
        text = element.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in text.split('\n') if line.strip() and len(line.strip()) > 10]
        return '\n'.join(lines)
    
    def close(self):
        """Close session"""
        self.session.close()


class SearchEngine:
    """Search engine with DEEP SCRAPING + CACHE + CONTEXT (v1.1)"""
    
    def __init__(self):
        self.query_optimizer = QueryOptimizer()
        self.deep_scraper = DeepScraper()
        self.cache = SearchCache(ttl_minutes=15)
        self.enricher = ContextualEnricher()
    
    def search(self, raw_query: str, max_results: int = 10, messages: List[Dict] = None) -> Dict:
        """Search with REAL content extraction + CACHE + CONTEXT"""
        
        # Step 1: Check cache first
        cached_result = self.cache.get(raw_query)
        if cached_result:
            return cached_result
        
        # Step 2: Enrich vague queries with conversation context
        enriched_query = raw_query
        context = ""
        if messages:
            enriched_query, context = self.enricher.enrich_query(raw_query, messages)
        
        # Step 3: Optimize the query
        optimized_query, query_type = self.query_optimizer.optimize(enriched_query)
        
        logger.info(f"[Sam] Searching: {optimized_query}")
        print(f"Optimizando búsqueda: '{optimized_query}'")
        
        try:
            # Use context manager to auto-close
            with DDGS() as ddgs:
                if query_type == "lyrics":
                    results = list(ddgs.text(optimized_query, region='wt-wt', safesearch='off', max_results=max_results))
                elif query_type == "news":
                    results = list(ddgs.text(optimized_query, region='mx-es', safesearch='moderate', timelimit='m', max_results=max_results))
                elif query_type == "price":
                    # PRIORITIZE MEXICO for price queries
                    results = list(ddgs.text(optimized_query, region='mx-es', safesearch='moderate', timelimit='y', max_results=max_results))
                else:
                    results = list(ddgs.text(optimized_query, region='mx-es', safesearch='moderate', max_results=max_results))
            
            logger.info(f"[Sam] Found {len(results)} results")
            
            # DEEP SCRAPE: Extract real content from URLs
            extracted_content = None
            
            # Filter relevant results
            relevant_results = self._filter_results(results, query_type)
            
            if query_type in ["lyrics", "general"]:
                # Try to extract from first 3 relevant results
                for result in relevant_results[:3]:
                    content_data = self.deep_scraper.extract_content(result['href'], query_type)
                    if content_data and content_data['length'] > 500:
                        extracted_content = content_data
                        logger.info(f"[Sam] ✅ Deep scrape successful: {content_data['length']} chars")
                        break
            
            result = {
                'original_query': raw_query,
                'enriched_query': enriched_query if enriched_query != raw_query else None,
                'optimized_query': optimized_query,
                'query_type': query_type,
                'results': relevant_results[:5],
                'extracted_content': extracted_content,
                'context': context if context else None
            }
            
            # Cache successful results
            self.cache.set(raw_query, result)
            
            return result
            
        except Exception as e:
            logger.error(f"[Sam] Search error: {e}")
            return {
                'original_query': raw_query,
                'optimized_query': optimized_query,
                'query_type': query_type,
                'results': [],
                'extracted_content': None,
                'error': str(e)
            }
    
    def _filter_results(self, results: List[Dict], query_type: str) -> List[Dict]:
        """Filter irrelevant results"""
        blacklist = ['zhihu.com', 'baidu.com', 'bilibili.com']
        
        filtered = []
        for r in results:
            url = r.get('href', '')
            
            # Block blacklisted
            if any(bl in url for bl in blacklist):
                continue
            
            # For lyrics, prefer known sites
            if query_type == "lyrics":
                known_sites = ['genius.com', 'letras.com', 'musixmatch.com', 'azlyrics.com', 'lyrics.com']
                title_lower = r.get('title', '').lower()
                
                is_known = any(site in url for site in known_sites)
                mentions_lyrics = 'lyrics' in title_lower or 'letra' in title_lower
                
                if is_known or mentions_lyrics:
                    filtered.append(r)
            else:
                filtered.append(r)
        
        return filtered
    
    def synthesize_results(self, search_response: Dict) -> str:
        """Synthesize with REAL content"""
        # If we have extracted content, use it
        if search_response.get('extracted_content'):
            content = search_response['extracted_content']
            
            # Show full extracted content
            if search_response['query_type'] == 'lyrics':
                return f"""Contenido extraído de: {content['url']}

{content['content']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fuente: {content.get('source', 'Web')}
"""
            
            # For other content, show full text
            return f"""Contenido extraído ({content['length']} caracteres):

{content['content']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fuente: {content['url']}"""
        
        # Fallback to snippets
        if not search_response.get('results'):
            return f"""No encontré resultados relevantes.

Búsqueda: {search_response['original_query']}"""
        
        snippets = []
        for i, r in enumerate(search_response['results'][:5], 1):
            snippets.append(f"{i}. {r['title']}\n   {r['body']}\n   {r['href']}")
        
        return '\n\n'.join(snippets)
    
    def close(self):
        """Close resources"""
        self.deep_scraper.close()
        self.cache.clear()
