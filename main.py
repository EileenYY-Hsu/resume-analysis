import os
import sys
import re
import json
import uuid
import configparser
from datetime import datetime, timedelta
import pandas as pd
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment, Font
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
import loadpdf
import gpt
import sqlite_db

analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

class PrivacyFilter:
    def __init__(self):
        self.mapping = {}
        
    def mask(self, text, extra_masks=None):
        if not analyzer or not anonymizer or not text:
            return text
            
        try:
            # 只針對真正敏感的個資(姓名、Email、電話)進行遮蔽，保留日期與連結等以便 LLM 精確提取
            results = analyzer.analyze(text=text, language='en', entities=['PERSON', 'EMAIL_ADDRESS', 'PHONE_NUMBER'])
            # 依賴位置偏移進行替換時，盡量使用 custom operator 來與預設引擎相容
            def replacer(txt):
                uid = uuid.uuid4().hex[:4]
                ph = f"<MASKED_{uid}>"
                self.mapping[ph] = txt
                return ph

            anonymizer_result = anonymizer.anonymize(
                text=text,
                analyzer_results=results,
                operators={"DEFAULT": OperatorConfig("custom", {"lambda": replacer})}
            )
            result_text = anonymizer_result.text
            
            # 手動追加遮蔽特定的字串 (例如 104 代碼)
            if extra_masks:
                for word in extra_masks:
                    if word and word in result_text:
                        uid = uuid.uuid4().hex[:4]
                        ph = f"<MASKED_104_{uid}>"
                        self.mapping[ph] = word
                        result_text = result_text.replace(word, ph)
                        
            return result_text
        except Exception as e:
            print(f"Masking error: {e}")
            return text

    def unmask(self, text):
        if not text:
            return text
        unmasked = str(text)
        for placeholder, original in self.mapping.items():
            unmasked = unmasked.replace(placeholder, original)
        return unmasked

# 自定義 Logger 類別，同時輸出到終端機與檔案
class DualLogger:
    def __init__(self, stream, file):
        self.stream = stream
        self.file = file
        # 用於過濾終端機 ANSI 上色控制碼，避免 log 檔被亂碼污染
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def write(self, message):
        try:
            self.stream.write(message)
        except UnicodeEncodeError:
            encoding = getattr(self.stream, 'encoding', 'ascii') or 'ascii'
            self.stream.write(message.encode(encoding, errors='replace').decode(encoding))
        clean_message = self.ansi_escape.sub('', message)
        self.file.write(clean_message)
        self.file.flush()

    def flush(self):
        self.stream.flush()
        self.file.flush()

# 確保日誌輸出目錄存在
output_dir = "output"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# 產生 Log 檔名 (output/log_MMDD_HHMM.txt)
log_filename = os.path.join(output_dir, f"log_{datetime.now().strftime('%m%d_%H%M')}.txt")
log_file = open(log_filename, "w", encoding='utf-8')

# 重導 stdout, stderr
sys.stdout = DualLogger(sys.stdout, log_file)
sys.stderr = DualLogger(sys.stderr, log_file)

def parse_json_response(response_str):
    """清理並解析 JSON，回傳 dict；若失敗回傳 None"""
    try:
        # 強健的 JSON 提取：尋找第一個 { 和最後一個 }
        match = re.search(r'(\{.*\}|\[.*\])', response_str, re.DOTALL)
        if match:
            clean_str = match.group(0)
        else:
            clean_str = re.sub(r'```json\s*|\s*```', '', response_str).strip()
            
        return json.loads(clean_str, strict=False)
    except Exception as e:
        print(f"⚠️ JSON 解析失敗。錯誤: {e}。內容前100字: {response_str[:100]}...")
        return None

# 提取履歷代碼的輔助函式 (用於比對與跳過)
def get_resume_code(subject, body):
    """從主旨與內文提取履歷代碼，用於去重與追蹤"""
    # 1. 先從主旨格式提取
    # 支援格式: 姓名_代碼 (如 林佳穎_Q7M2RA8KX)
    subject_match_underscore = re.search(r'_(?P<code>[a-zA-Z0-9]+)$', subject)
    if subject_match_underscore:
        return subject_match_underscore.group('code')
        
    # 支援格式: 姓名 (代碼) (如 姓名 (XXXXXXXX))
    subject_match_paren = re.search(r'\((?P<code>[a-zA-Z0-9]{8,15})\)', subject)
    if subject_match_paren:
        return subject_match_paren.group('code')
    
    # 2. 從內文特定的標籤/欄位提取
    body_patterns = [
        r'(?:個資|履歷|應徵)?\s*代碼\s*[：:]\s*(?P<code>[a-zA-Z0-9]+)',
        r'(?:Apply|Resume)?\s*Code\s*[：:]\s*(?P<code>[a-zA-Z0-9]+)',
        r'id=(?P<code>[a-zA-Z0-9]{12,})'
    ]
    for pattern in body_patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group('code').strip()
    return None

# 確保資料庫結構已初始化
sqlite_db.init_db()

# 讀取系統設定檔
config = configparser.ConfigParser()
config.read('config_run.ini', encoding='utf-8')

# 載入 PDF 履歷並取得資料庫內既有的履歷代碼 (避免重複處理)
existing_codes = sqlite_db.get_existing_codes()
messages = loadpdf.loadpdf()

# 預先掃描，計算需處理與可跳過的檔案數量
final_process_list = []
skipped_count = 0
for msg in messages:
    code = get_resume_code(msg.Subject, msg.Body)
    if not code:
        # 如果無法解析出代碼，則使用檔名作為備用 unique code
        code = msg.Subject
        
    if code in existing_codes:
        skipped_count += 1
    else:
        final_process_list.append((msg, code))

# --- 終端機狀態摘要 ---
print(f"✅ 成功取得 {len(messages)} 份 PDF 履歷")
print(f"⏭️  已跳過 {skipped_count} 份重複履歷 (資料庫已存在)")
print(f"📝 本次分析 {len(final_process_list)} 份新進 PDF 履歷")
print(f"📊 目前資料庫中已有 {len(existing_codes)} 筆履歷資料\n")

# 讀取職缺描述 (JD) 檔案作為 GPT 評分依據
jd_filename = "JD.json"
try:
    jd_filename = config.get('FILES', 'jd_file').split('#')[0].strip()
    with open(jd_filename, 'r', encoding='utf-8') as f:
        jd_text = f.read()
    print(f"✅ 成功讀取 JD 檔案：{jd_filename}\n")
except Exception as e:
    print(f"❌ 讀取 JD 檔案失敗 ({jd_filename}): {e}")
    exit()

# 初始化結果容器
all_resumes_data = []      # 成功解析的履歷資料
skipped_parsing_list = []  # 解析失敗需跳過的信件

print(f"🚀 開始執行處理程序 (共 {len(messages)} 份)...\n")
print("="*50)

for i, msg in enumerate(messages):
    try:
        subject = msg.Subject
        resume_text = f"履歷名稱: {subject}\n\n履歷內容:\n{msg.Body}"
        
        # 提取代碼進行比對
        found_code = get_resume_code(subject, msg.Body)
        if not found_code:
            found_code = subject
        
        if found_code in existing_codes:
            print(f"[{i+1}/{len(messages)}] ⏩ 跳過 (資料庫已存在): {subject}")
            continue

        # 確認為新履歷後，準備交給 GPT 分析
        if found_code == subject:
            print(f"[{i+1}/{len(messages)}] 🚀 發現新進履歷 (無法預提取代碼，使用檔名作為 ID: {found_code})，交由 GPT 分析: {subject}")
        else:
            print(f"[{i+1}/{len(messages)}] 🔍 發現新進履歷：{subject}，開始分析...")
        
        # 呼叫 GPT 進行分析
        max_retries = 0
        success = False
        resume_data = {}

        # 注入時間參考資訊，幫助 GPT 判斷年資
        current_time_ref = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mail_meta_time = msg.ReceivedTime.strftime("%Y-%m-%d %H:%M:%S")
        enhanced_content = (
            f"【系統參考時間】: {current_time_ref}\n"
            f"【履歷接收時間】: {mail_meta_time}\n"
            f"{resume_text}"
        )

        # 在傳給 GPT 前使用 PrivacyFilter 遮蔽機敏資訊 (包含自訂提取出的代碼)
        privacy_filter = PrivacyFilter()
        extra_sensitive_words = [found_code] if found_code else None
        masked_content = privacy_filter.mask(enhanced_content, extra_masks=extra_sensitive_words)

        for attempt in range(max_retries + 1):
            # 請求 GPT 分析履歷與 JD 的匹配度 (傳入已經遮蔽的內容)
            result = gpt.analyze_resume(masked_content, jd_text)
            
            # 將 GPT 回傳的 JSON 字串中的代碼還原成真實資訊
            unmasked_info = privacy_filter.unmask(result.get('info', ''))
            unmasked_summary = privacy_filter.unmask(result.get('summary', ''))
            unmasked_match = privacy_filter.unmask(result.get('match_score', ''))
            
            # 將還原後的 JSON 格式字串轉為 Python 字典
            info_json = parse_json_response(unmasked_info)
            sum_json = parse_json_response(unmasked_summary)
            match_json = parse_json_response(unmasked_match)
            
            # 判斷是否解析成功
            if info_json is not None and sum_json is not None and match_json is not None:
                # 將 GPT 按 prompt 規定輸出的字串 "None" 轉回空字串，使後續的 or fallback 邏輯順利觸發
                for json_dict in [info_json, sum_json, match_json]:
                    for k, v in json_dict.items():
                        if isinstance(v, str) and v.strip() == "None":
                            json_dict[k] = ""

                # 組合單筆資料 (使用 'or' 確保解析若為 null 時，能觸發預設空字串 fallback)
                resume_data = {
                    "interview_state": "", 
                    "is_screened": "未儲存",
                    "name": (info_json.get("name") or "").strip(),
                    "code": (found_code if found_code and found_code != subject else info_json.get("code")) or found_code or "",
                    "age": info_json.get("age") or "",
                    "total_work_years": info_json.get("total_work_years") or "",
                    "it_work_years": info_json.get("it_work_years") or "",
                    "autobiography": sum_json.get("autobiography") or "",
                    "work_experience": sum_json.get("work_experience") or "",
                    "highest_edu_level": info_json.get("highest_edu_level") or "",
                    "highest_edu_school": info_json.get("highest_edu_school") or "",
                    "highest_edu_major": info_json.get("highest_edu_major") or "",
                    "highest_edu_period": info_json.get("highest_edu_period") or "",
                    "second_edu_school": info_json.get("second_edu_school") or "",
                    "second_edu_major": info_json.get("second_edu_major") or "",
                    "tech_skills": sum_json.get("tech_skills") or "",
                    "key_highlights": sum_json.get("key_highlights") or "",
                    "notes": sum_json.get("notes") or "",
                    "score": match_json.get("score") or "",
                    "reason": match_json.get("reason") or "",
                    "score_data_eng": match_json.get("score_data_eng") or "",
                    "score_db_sql": match_json.get("score_db_sql") or "",
                    "score_ai_app": match_json.get("score_ai_app") or "",
                    "score_rag_sys": match_json.get("score_rag_sys") or "",
                    "score_deployment": match_json.get("score_deployment") or ""
                }
                success = True
                break
            else:
                # 解析不完整時的失敗處理 (不再重試，直接準備跳過與清理)
                current_code = found_code or (info_json and info_json.get("code"))
                print(f"   ❌ 解析失敗，跳過此履歷。")
                
                skipped_parsing_list.append({"subject": subject, "code": current_code})

                if current_code:
                    print(f"   [Cleanup] 解析不完整，確保刪除資料庫紀錄 ({current_code})")
                    sqlite_db.delete_resume(current_code)
                
                break
        
        if not success:
            continue

        all_resumes_data.append(resume_data)

        # 顯示結果摘要
        print(f"   ---> 匹配分數: {resume_data['score']}")
        print(f"   ---> 理由: {resume_data['reason']}")
        print(f"   ---> 履歷亮點: {resume_data['key_highlights']}") 
        
        # 寫入資料庫
        sqlite_db.save_resume(resume_data)
        
        # 即時更新已讀清單
        if resume_data["code"]:
            existing_codes.add(resume_data["code"])
            
        print("-" * 50)
        
    except Exception as e:
        print(f"❌ 處理履歷失敗 ({subject}): {e}")
        continue

# 處理 DataFrame 並存檔
print("\n📊 正在將資料轉換為 Excel...")
if all_resumes_data:
    df = pd.DataFrame(all_resumes_data)
    
    # 定義 DataFrame 欄位名稱與最終 Excel 標題的對照表
    column_mapping = {
        "interview_state": "邀約面試狀態",
        "is_screened": "是否篩選",
        "name": "姓名",
        "code": "代碼",
        "age": "年齡",
        "total_work_years": "總工作年資",
        "it_work_years": "資訊類工作年資",
        "autobiography": "自傳",
        "work_experience": "工作經歷",
        "highest_edu_level": "最高學歷",
        "highest_edu_school": "最高學歷學校",
        "highest_edu_major": "最高學歷科系",
        "highest_edu_period": "最高學歷期間",
        "second_edu_school": "次高學歷學校",
        "second_edu_major": "次高學歷科系",
        "tech_skills": "資訊類相關專長",
        "key_highlights": "履歷亮點",
        "notes": "備註",
        "score_data_eng": "資料工程能力評估",
        "score_db_sql": "資料庫與 SQL 能力評估",
        "score_ai_app": "AI 應用能力評估",
        "score_rag_sys": "RAG 與系統整合能力評估",
        "score_deployment": "平台部署與工程能力評估",
        "score": "總分",
        "reason": "理由"
    }
    
    # 定義欄位順序 (使用英文 Key)
    columns_order = list(column_mapping.keys())
    
    # 重新排序並重新命名
    df = df[columns_order].rename(columns=column_mapping)
    
    # 生成包含日期的檔名 (output/履歷整理_MMDD_HHMM.xlsx)
    current_date_str = datetime.now().strftime("%m%d_%H%M")
    output_file = os.path.join(output_dir, f"履歷整理_{current_date_str}.xlsx")
    
    try:
        # 使用 ExcelWriter 進行格式設定
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='履歷分析')
            
            # 取得 workbook 和 worksheet 物件
            workbook = writer.book
            worksheet = writer.sheets['履歷分析']
            header_font = Font(bold=True)
            
            # 定義需要固定寬度並換行的欄位 (使用者指定列表)
            fixed_width_columns = ["自傳", "工作經歷", "資訊類相關專長", "履歷亮點", "備註", "理由"]
            fixed_width_val = 80  # Excel 欄寬 80
            
            # 定義評分細節欄位
            score_detail_columns = ["資料工程能力評估", "資料庫與 SQL 能力評估", "AI 應用能力評估", "RAG 與系統整合能力評估", "平台部署與工程能力評估"]
            score_detail_val = 40

            # 設定欄寬與換行
            for i, col_name in enumerate(df.columns, 1):
                col_letter = get_column_letter(i)
                
                if col_name in fixed_width_columns:
                    # 指定長文欄位：固定寬度 80
                    worksheet.column_dimensions[col_letter].width = fixed_width_val
                    # 設定自動換行
                    for cell in worksheet[col_letter]:
                        cell.alignment = Alignment(wrap_text=True, vertical='top')
                
                elif col_name in score_detail_columns:
                    # 評分細節欄位：固定寬度 40
                    worksheet.column_dimensions[col_letter].width = score_detail_val
                    # 設定自動換行
                    for cell in worksheet[col_letter]:
                        cell.alignment = Alignment(wrap_text=True, vertical='top')

                elif col_name == "總分":
                    # 評分欄位：縮短寬度並置中
                    worksheet.column_dimensions[col_letter].width = 8
                    for cell in worksheet[col_letter]:
                        cell.alignment = Alignment(horizontal='center', vertical='center')

                else:
                    # 其他欄位：自動調整寬度 (Auto-fit) 以顯示完整內容
                    max_length = 0
                    
                    # 包含標題列一起計算
                    cells = [worksheet[f"{col_letter}1"]] + list(worksheet[col_letter])[1:]
                    
                    for cell in cells:
                        try:
                            val = cell.value
                            if val:
                                str_val = str(val)
                                # 計算視覺長度：中文/全形算 2，英文/半形算 1
                                local_len = 0
                                for char in str_val:
                                    if ord(char) > 127: # 簡單判斷非 ASCII 字元
                                        local_len += 2
                                    else:
                                        local_len += 1
                                
                                if local_len > max_length:
                                    max_length = local_len
                        except:
                            pass
                    
                    # 設定寬度 (加一點緩衝空間)
                    adjusted_width = max_length + 2
                    worksheet.column_dimensions[col_letter].width = adjusted_width
                    
                    # 其他欄位僅設定垂直置中
                    for cell in worksheet[col_letter]:
                        if not cell.alignment.wrap_text:
                            cell.alignment = Alignment(vertical='center')

                # 標題列統一置中
                header_cell = worksheet[f"{col_letter}1"]
                header_cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                header_cell.font = header_font

        print(f"✅ 已成功儲存分析結果至: {output_file}")
    except Exception as e:
        print(f"❌ 儲存 Excel 失敗: {e}")
else:
    print("⚠️ 沒有資料可以產出 Excel。")
        
print("\n✅ 所有履歷分析完成！")

# 顯示解析失敗的總結
if skipped_parsing_list:
    print("\n⚠️ 以下履歷因解析失敗而跳過 (已從資料庫刪除/未寫入):")
    for skip_item in skipped_parsing_list:
        skip_subj = skip_item["subject"]
        skip_code = skip_item["code"] or "無法取得代碼"
        print(f"   - [{skip_code}] {skip_subj}")
else:
    print("\n✨ 所有履歷均成功解析！")

# MySQL 資料已寫入，可使用 MySQL 客戶端查看
print(f"\n✅ Log 檔已儲存: {log_filename}")
