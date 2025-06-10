#!/usr/bin/env python3
"""
Columbus Dispatch Morning Summary Scraper
Scrapes articles, summarizes with DeepSeek API, and sends beautiful email summaries
"""
import requests
from bs4 import BeautifulSoup
import resend
from datetime import datetime
import time
import json
import os
from typing import List, Dict
import logging
import re

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ColumbusDispatchScraper:
    def __init__(self, deepseek_api_key: str, resend_api_key: str, from_email: str, to_email: str):
        self.deepseek_api_key = deepseek_api_key
        self.resend_api_key = resend_api_key
        self.from_email = from_email
        self.to_email = to_email
        self.base_url = "https://www.dispatch.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Set up Resend API key
        resend.api_key = self.resend_api_key
        
    def scrape_articles(self, max_articles: int = 10) -> List[Dict[str, str]]:
        """Scrape latest articles from Columbus Dispatch"""
        try:
            response = requests.get(self.base_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            articles = []
            
            # Look for article links (adjust selectors based on site structure)
            article_links = soup.find_all('a', href=True)
            processed_urls = set()
            
            for link in article_links:
                href = link.get('href')
                if not href:
                    continue
                    
                # Filter for news articles
                if any(keyword in href.lower() for keyword in ['/story/', '/news/', '/sports/', '/business/']):
                    if href.startswith('/'):
                        full_url = self.base_url + href
                    else:
                        full_url = href
                        
                    if full_url not in processed_urls and len(articles) < max_articles:
                        title = link.get_text(strip=True)
                        if title and len(title) > 10:  # Filter out short/empty titles
                            articles.append({
                                'title': title,
                                'url': full_url,
                                'content': ''
                            })
                            processed_urls.add(full_url)
            
            # Get article content
            for article in articles:
                try:
                    article['content'] = self.get_article_content(article['url'])
                    time.sleep(1)  # Be respectful to the server
                except Exception as e:
                    logger.warning(f"Failed to get content for {article['url']}: {e}")
                    
            return articles
            
        except Exception as e:
            logger.error(f"Error scraping articles: {e}")
            return []
    
    def get_article_content(self, url: str) -> str:
        """Extract article content from URL"""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Common selectors for article content
            content_selectors = [
                'div.article-body',
                'div.story-body',
                'div.entry-content',
                'article p',
                'div.content p'
            ]
            
            content = ""
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    content = ' '.join([elem.get_text(strip=True) for elem in elements])
                    break
            
            # Fallback: get all paragraph text
            if not content:
                paragraphs = soup.find_all('p')
                content = ' '.join([p.get_text(strip=True) for p in paragraphs[:10]])
            
            return content[:2000]  # Limit content length
            
        except Exception as e:
            logger.error(f"Error getting article content from {url}: {e}")
            return ""
    
    def summarize_with_deepseek(self, articles: List[Dict[str, str]]) -> str:
        """Summarize articles using DeepSeek API with retry logic"""
        # Prepare content for summarization
        content_for_summary = ""
        for i, article in enumerate(articles, 1):
            content_for_summary += f"\n\nArticle {i}: {article['title']}\n{article['content'][:500]}"
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a friendly local news summarizer for Columbus, Ohio residents. Create a warm, engaging summary that makes people feel connected to their community. Focus on the most important local stories and present them in a conversational, optimistic tone that helps start the day positively."
                },
                {
                    "role": "user",
                    "content": f"Please create a warm, engaging morning summary of these Columbus Dispatch articles. Group similar topics together and highlight what matters most to Columbus residents. Keep it informative but uplifting:\n{content_for_summary}"
                }
            ],
            "temperature": 0.7,
            "max_tokens": 800
        }
        
        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }
        
        # Try multiple times with different timeouts
        for attempt in range(3):
            try:
                timeout = 30 + (attempt * 15)  # 30s, 45s, 60s
                logger.info(f"Attempting DeepSeek API call (attempt {attempt + 1}/3, timeout: {timeout}s)")
                
                response = requests.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=timeout
                )
                response.raise_for_status()
                
                result = response.json()
                summary = result['choices'][0]['message']['content']
                logger.info("Successfully generated summary with DeepSeek API")
                return summary
                
            except requests.exceptions.Timeout:
                logger.warning(f"DeepSeek API timeout on attempt {attempt + 1}")
                if attempt < 2:  # Don't sleep after last attempt
                    time.sleep(5)
                continue
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"DeepSeek API request error on attempt {attempt + 1}: {e}")
                if attempt < 2:
                    time.sleep(5)
                continue
                    
            except Exception as e:
                logger.error(f"Unexpected error with DeepSeek API on attempt {attempt + 1}: {e}")
                if attempt < 2:
                    time.sleep(5)
                continue
        
        # If all attempts failed, create a basic summary from article titles
        logger.warning("All DeepSeek API attempts failed, creating basic summary from titles")
        return self.create_fallback_summary(articles)
    
    def create_fallback_summary(self, articles: List[Dict[str, str]]) -> str:
        """Create a basic summary when AI API fails"""
        today = datetime.now().strftime("%B %d, %Y")
        
        summary = f"""Good morning, Columbus! ☀️

While our AI summarizer is taking a coffee break, here's what's happening in our city today ({today}):

📰 <strong>Top Stories from The Columbus Dispatch:</strong>

"""
        
        # Group articles by likely categories
        categories = {
            'Local News': [],
            'Sports': [],
            'Business': [],
            'Other': []
        }
        
        for article in articles[:8]:
            title_lower = article['title'].lower()
            if any(word in title_lower for word in ['columbus', 'ohio', 'local', 'city', 'county']):
                categories['Local News'].append(article['title'])
            elif any(word in title_lower for word in ['sports', 'game', 'team', 'player', 'score']):
                categories['Sports'].append(article['title'])
            elif any(word in title_lower for word in ['business', 'economy', 'market', 'company']):
                categories['Business'].append(article['title'])
            else:
                categories['Other'].append(article['title'])
        
        # Add categorized articles to summary
        for category, titles in categories.items():
            if titles:
                summary += f"\n🏷️ <strong>{category}:</strong><br>\n"
                for title in titles[:3]:  # Limit to 3 per category
                    summary += f"• {title}<br>\n"
                summary += "<br>\n"
        
        summary += """Stay informed, stay connected, and have a wonderful day in Columbus! 🌆<br><br>

Check out the full articles below for all the details."""
        
        return summary
    
    def convert_markdown_to_html(self, text: str) -> str:
        """Convert basic markdown formatting to HTML"""
        # Convert headers (### Header -> <h3>Header</h3>)
        text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
        text = re.sub(r'^# (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)
        
        # Convert bold text (**text** -> <strong>text</strong>)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        
        # Convert italic text (*text* -> <em>text</em>)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        
        # Convert line breaks to HTML
        text = text.replace('\n', '<br>')
        
        # Fix double line breaks for paragraphs
        text = re.sub(r'<br><br>', '</p><p>', text)
        text = f'<p>{text}</p>'
        
        # Clean up empty paragraphs
        text = re.sub(r'<p></p>', '', text)
        text = re.sub(r'<p><br></p>', '', text)
        
        return text
    
    def create_beautiful_email(self, summary: str, articles: List[Dict[str, str]]) -> str:
        """Create a beautifully formatted HTML email"""
        today = datetime.now().strftime("%B %d, %Y")
        
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: 'Georgia', serif;
                    line-height: 1.6;
                    margin: 0;
                    padding: 0;
                    background-color: #f8f9fa;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background-color: white;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                }}
                .header {{
                    background: linear-gradient(135deg, #2c3e50, #34495e);
                    color: white;
                    text-align: center;
                    padding: 40px 20px;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 28px;
                    font-weight: 300;
                }}
                .date {{
                    font-size: 16px;
                    opacity: 0.9;
                    margin-top: 10px;
                }}
                .greeting {{
                    background-color: #3498db;
                    color: white;
                    text-align: center;
                    padding: 20px;
                    font-size: 18px;
                }}
                .summary {{
                    padding: 30px;
                    background-color: #fff;
                }}
                .summary h2 {{
                    color: #2c3e50;
                    border-bottom: 3px solid #3498db;
                    padding-bottom: 10px;
                    margin-bottom: 20px;
                }}
                .summary-content {{
                    font-size: 16px;
                    color: #444;
                    line-height: 1.8;
                }}
                .articles-section {{
                    background-color: #f8f9fa;
                    padding: 30px;
                }}
                .articles-section h3 {{
                    color: #2c3e50;
                    margin-bottom: 20px;
                    font-size: 20px;
                }}
                .article-item {{
                    background: white;
                    margin-bottom: 15px;
                    border-left: 4px solid #3498db;
                    padding: 15px 20px;
                    border-radius: 0 5px 5px 0;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                }}
                .article-title {{
                    font-weight: bold;
                    margin-bottom: 5px;
                }}
                .article-title a {{
                    color: #2c3e50;
                    text-decoration: none;
                }}
                .article-title a:hover {{
                    color: #3498db;
                }}
                .footer {{
                    background-color: #2c3e50;
                    color: white;
                    text-align: center;
                    padding: 25px;
                    font-size: 14px;
                }}
                .columbus-love {{
                    background: linear-gradient(135deg, #e74c3c, #c0392b);
                    color: white;
                    text-align: center;
                    padding: 20px;
                    font-style: italic;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🌅 Good Morning, Columbus!</h1>
                    <div class="date">{today}</div>
                </div>
                
                <div class="greeting">
                    ☕ Your daily dose of local news, served fresh
                </div>
                
                <div class="summary">
                    <h2>📰 Today's Highlights</h2>
                    <div class="summary-content">
                        {self.convert_markdown_to_html(summary)}
                    </div>
                </div>
                
                <div class="articles-section">
                    <h3>🔗 Full Articles</h3>
        """
        
        for article in articles[:8]:
            html_template += f"""
                    <div class="article-item">
                        <div class="article-title">
                            <a href="{article['url']}" target="_blank">{article['title']}</a>
                        </div>
                    </div>
            """
        
        html_template += f"""
                </div>
                
                <div class="columbus-love">
                    💝 Stay connected, Columbus. Have a wonderful day!
                </div>
                
                <div class="footer">
                    <p>This summary was lovingly crafted by your personal Columbus news assistant</p>
                    <p>Source: The Columbus Dispatch | Generated: {datetime.now().strftime("%I:%M %p")}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_template
    
    def send_email(self, html_content: str):
        """Send the formatted email using Resend API"""
        try:
            r = resend.Emails.send({
                "from": self.from_email,
                "to": self.to_email,
                "subject": f"🌅 Your Columbus Morning Brief - {datetime.now().strftime('%B %d, %Y')}",
                "html": html_content
            })
            
            logger.info(f"Email sent successfully! Resend ID: {r.get('id', 'N/A')}")
            
        except Exception as e:
            logger.error(f"Error sending email with Resend: {e}")
    
    def run_daily_summary(self):
        """Main function to run the daily summary"""
        logger.info("Starting Columbus Dispatch morning summary...")
        
        # Scrape articles
        articles = self.scrape_articles()
        if not articles:
            logger.warning("No articles found")
            return
            
        logger.info(f"Found {len(articles)} articles")
        
        # Generate summary
        summary = self.summarize_with_deepseek(articles)
        
        # Create and send email
        html_content = self.create_beautiful_email(summary, articles)
        self.send_email(html_content)
        
        logger.info("Daily summary completed!")

def main():
    # Configuration
    config = {
        'deepseek_api_key': os.getenv('DEEPSEEK_API_KEY', 'your-deepseek-api-key-here'),
        'resend_api_key': os.getenv('RESEND_API_KEY', 'your-resend-api-key-here'),
        'from_email': os.getenv('FROM_EMAIL', 'onboarding@resend.dev'),
        'to_email': os.getenv('TO_EMAIL', 'your-email@gmail.com')
    }
    
    # Create scraper instance
    scraper = ColumbusDispatchScraper(
        deepseek_api_key=config['deepseek_api_key'],
        resend_api_key=config['resend_api_key'],
        from_email=config['from_email'],
        to_email=config['to_email']
    )
    
    # Run the daily summary
    scraper.run_daily_summary()

if __name__ == "__main__":
    main()
