<<<<<<< HEAD
import requests

def fetch_stock_news(stock_code):
    """
    模拟获取股票新闻。实战中可接入财联社、新浪财经或简单的搜索接口。
    """
    # 示例：如果是半导体板块，Gemini 会自动识别
    # 你可以根据 code 在这里接入实际的爬虫逻辑
    return f"该股票近期涉及半导体集成电路研发突破，且有大宗交易记录。"

def send_push(title, content):
    """PushDeer 发送函数"""
    PUSH_URL = "https://api2.pushdeer.com/message/push"
    KEY = "你的_PUSHDEER_KEY"
=======
import requests

def fetch_stock_news(stock_code):
    """
    模拟获取股票新闻。实战中可接入财联社、新浪财经或简单的搜索接口。
    """
    # 示例：如果是半导体板块，Gemini 会自动识别
    # 你可以根据 code 在这里接入实际的爬虫逻辑
    return f"该股票近期涉及半导体集成电路研发突破，且有大宗交易记录。"

def send_push(title, content):
    """PushDeer 发送函数"""
    PUSH_URL = "https://api2.pushdeer.com/message/push"
    KEY = "你的_PUSHDEER_KEY"
>>>>>>> 25037b06f3249fc02a71417fb0670911acd894f5
    requests.get(PUSH_URL, params={"pushkey": KEY, "text": title, "desp": content})