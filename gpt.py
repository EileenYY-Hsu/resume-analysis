import configparser
from openai import OpenAI

class GPTAnalyzer:
    def __init__(self, config_file='config.ini', prompt_file='prompts.md'):
        self.config = configparser.ConfigParser()
        self.config.read(config_file, encoding='utf-8')
        
        # 讀取 API 設定
        self.api_key = self.config.get('API', 'api_key').split('#')[0].strip()
        self.model = self.config.get('API', 'model').split('#')[0].strip()
        
        # 初始化 OpenAI 客戶端
        self.client = OpenAI(api_key=self.api_key)
        
        # 讀取 Prompts from Markdown file
        self.prompts = self._read_markdown_prompts(prompt_file)

        self.prompt_info = self.prompts.get('prompt_info', '')
        self.prompt_sum = self.prompts.get('prompt_sum', '')
        self.prompt_match = self.prompts.get('prompt_match', '')

        self.system_info = self.prompts.get('system_info', '')
        self.system_sum = self.prompts.get('system_sum', '')
        self.system_match = self.prompts.get('system_match', '')

    def _read_markdown_prompts(self, prompt_file):
        """從 markdown 檔案讀取 prompt 設定"""
        prompts = {}
        current_key = None
        current_lines = []

        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.rstrip() # remove trailing newline
                    if line.startswith('## '):
                        if current_key:
                            prompts[current_key] = '\n'.join(current_lines).strip()
                        current_key = line[3:].strip()
                        current_lines = []
                    elif current_key:
                        current_lines.append(line)
                
                # add the last section
                if current_key:
                    prompts[current_key] = '\n'.join(current_lines).strip()
        except FileNotFoundError:
            print(f"警告: 找不到 {prompt_file}，請確認檔案存在。")
        except Exception as e:
            print(f"讀取 Prompt 檔案錯誤: {e}")
            
        return prompts

    def get_gpt_response(self, prompt, content, system_prompt):
        """
        發送請求給 GPT 並取得回應
        """
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{prompt}\n\n內容如下：\n{content}"}
            ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,  # 降低隨機性，讓提取結果更穩定
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"GPT Error: {str(e)}"

    def analyze(self, resume_content, jd_content):
        """
        執行完整的分析流程：
        1. 提取基本資訊 (info)
        2. 提取提要 (sum)
        3. 與 JD 進行匹配評分 (match)
        """
        print(f"   [GPT] 正在提取基本資訊...")
        info_result = self.get_gpt_response(self.prompt_info, resume_content, self.system_info)
        
        print(f"   [GPT] 正在生成履歷提要...")
        sum_result = self.get_gpt_response(self.prompt_sum, resume_content, self.system_sum)
        
        print(f"   [GPT] 正在計算匹配分數...")
        # 組合匹配所需的 context：JD + (基本資訊 + 提要)
        match_context = (
            f"【職缺描述 (JD)】：\n{jd_content}\n\n"
            f"【候選人基本資訊】：\n{info_result}\n\n"
            f"【候選人履歷提要】：\n{sum_result}"
        )
        match_result = self.get_gpt_response(self.prompt_match, match_context, self.system_match)
        
        # 將三個結果合併並回傳
        return {
            "info": info_result,
            "summary": sum_result,
            "match_score": match_result
        }

def analyze_resume(resume_text, jd_text):
    """
    提供給 main 呼叫的外部介面
    """
    analyzer = GPTAnalyzer()
    return analyzer.analyze(resume_text, jd_text)
