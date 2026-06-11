import configparser
import glob
import os
from datetime import datetime
import pypdf

class LocalPDF:
    def __init__(self, subject, body, received_time, file_path):
        self.Subject = subject or ""
        self.Body = body or ""
        self.ReceivedTime = received_time
        self.FilePath = file_path


def loadpdf():
    """
    讀取本機 .pdf 檔案，並回傳符合結構的履歷清單。
    """
    config = configparser.ConfigParser()
    config.read('config_run.ini', encoding='utf-8')

    pdf_folder = config.get('FOLDERS', 'pdf_folder', fallback='pdf_resumes').strip()

    if not os.path.isabs(pdf_folder):
        pdf_folder = os.path.join(os.path.dirname(__file__), pdf_folder)

    if not os.path.isdir(pdf_folder):
        os.makedirs(pdf_folder, exist_ok=True)
        print(f"無法找到 pdf_folder，已自動建立該資料夾：{pdf_folder}")

    pdf_paths = sorted(glob.glob(os.path.join(pdf_folder, '*.pdf')))
    filtered_resumes = []

    for file_path in pdf_paths:
        filename = os.path.basename(file_path)
        subject, _ = os.path.splitext(filename)
        
        # 讀取 PDF 內容
        body = ""
        try:
            reader = pypdf.PdfReader(file_path)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    body += text + "\n"
        except Exception as e:
            print(f"⚠️ 讀取 PDF 檔案失敗 ({filename}): {e}")
            continue

        # 使用檔案修改時間作為 ReceivedTime
        mtime = os.path.getmtime(file_path)
        received_time = datetime.fromtimestamp(mtime)

        filtered_resumes.append(LocalPDF(subject, body, received_time, file_path))

    # 依修改時間排序，新的在前
    filtered_resumes.sort(key=lambda x: x.ReceivedTime, reverse=True)
    return filtered_resumes
