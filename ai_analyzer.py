<<<<<<< HEAD
from google import genai
import os

def get_ai_score(code, tech_signal):
    prompt = f"分析 {code}，信号: {tech_signal}。输出JSON: {{\"score\": 80, \"reason\": \"str\", \"recommend\": bool}}"
    try:
        # 新版 API 调用方式
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
        )
        # 解析逻辑保持不变...
        return response.text
    except Exception as e:
=======
from google import genai
import os

def get_ai_score(code, tech_signal):
    prompt = f"分析 {code}，信号: {tech_signal}。输出JSON: {{\"score\": 80, \"reason\": \"str\", \"recommend\": bool}}"
    try:
        # 新版 API 调用方式
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
        )
        # 解析逻辑保持不变...
        return response.text
    except Exception as e:
>>>>>>> 25037b06f3249fc02a71417fb0670911acd894f5
        return {"score": 0, "reason": f"分析失败: {e}", "recommend": False}