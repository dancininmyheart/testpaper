import os
import time
import requests
import zipfile
import json
from io import BytesIO
import glob
from openai import OpenAI

# Mineru API Configuration
MINERU_TOKEN = "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiI2MjQwMTU5OCIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3NjMwNjk1OSwiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiMTM3OTg2MDIwNjkiLCJvcGVuSWQiOm51bGwsInV1aWQiOiIyODUzMmZmYi01MzM1LTRkNjItODhiNC0xMjdlYzc1YWRlYjAiLCJlbWFpbCI6IjExMzkwNjE1MjVAcXEuY29tIiwiZXhwIjoxNzg0MDgyOTU5fQ.2cP9TA3sKRpFBIfRYy30BVVmh5MKSAmtCb-A-G6p2XJB81awvOjF5CG2T0kxd0j9pfsaOBuLXo-wb-o6gQGIOw"
MINERU_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {MINERU_TOKEN}"
}

API_KEY_ZHICHUANG = "sk-u7ACbqmaQ5Ij187iYT9fUjwYsjIGcZi1qQtfHMXXKuu0TALc"
BASE_URL_ZHICHUANG = "https://s.lconai.com/v1"
MODEL_ZHICHUANG = "gpt-4o-mini"

def upload_and_parse_pdf(pdf_path):
    print(f"开始处理PDF文件: {pdf_path}")
    url = "https://mineru.net/api/v4/file-urls/batch"
    filename = os.path.basename(pdf_path)
    data = {
        "files": [
            {"name": filename, "data_id": "pdf_test_id"}
        ],
        "model_version": "vlm"
    }

    response = requests.post(url, headers=MINERU_HEADERS, json=data)
    if response.status_code == 200:
        result = response.json()
        if result["code"] == 0:
            batch_id = result["data"]["batch_id"]
            upload_urls = result["data"]["file_urls"]
            
            print(f"成功获取 batch_id: {batch_id}，开始上传文件...")
            with open(pdf_path, 'rb') as f:
                res_upload = requests.put(upload_urls[0], data=f)
                if res_upload.status_code == 200:
                    print("文件上传成功！")
                    return batch_id
                else:
                    raise Exception(f"文件上传失败: {res_upload.status_code}")
        else:
            raise Exception(f"获取上传URL失败: {result['msg']}")
    else:
        raise Exception(f"请求失败: {response.status_code}, {response.text}")

def wait_for_result(batch_id):
    print("开始轮询解析结果...")
    url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
    
    while True:
        res = requests.get(url, headers=MINERU_HEADERS)
        if res.status_code == 200:
            result = res.json()
            if result["code"] == 0:
                extract_data = result["data"]["extract_result"][0]
                state = extract_data.get("state")
                
                print(f"当前状态: {state}")
                if state == "done":
                    return extract_data["full_zip_url"]
                elif state == "failed":
                    raise Exception(f"解析失败: {extract_data.get('err_msg')}")
                elif state == "unreachable":
                    raise Exception("解析不可达")
            else:
                print(f"获取解析结果发生错误: {result['msg']}")
        else:
            print(f"请求解析结果失败: {res.status_code}")
        
        time.sleep(5)

def download_and_extract_md(zip_url, extract_to="output_dir"):
    print(f"下载解析结果 zip: {zip_url}")
    response = requests.get(zip_url)
    if response.status_code == 200:
        os.makedirs(extract_to, exist_ok=True)
        # 解压 zip
        with zipfile.ZipFile(BytesIO(response.content)) as zip_ref:
            zip_ref.extractall(extract_to)
        
        # 查找md文件
        md_files = []
        for root, dirs, files in os.walk(extract_to):
            for file in files:
                if file.endswith('.md'):
                    md_files.append(os.path.join(root, file))
                    
        if md_files:
            md_path = md_files[0]
            print(f"找到 Markdown 文件: {md_path}")
            with open(md_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            raise Exception("ZIP文件中未找到Markdown文件")
    else:
        raise Exception(f"下载ZIP失败: {response.status_code}")

def extract_questions_with_agent(md_content):
    print("开始调用 LLM Agent 提取试卷信息...")
    # NOTE: 需要配置好 openai / deepseek 等平台的 API KEY
    # 这里以常见的兼容 OpenAI 接口的模型为例
    
    api_key = API_KEY_ZHICHUANG
    base_url = BASE_URL_ZHICHUANG
    
    # 也可以直接在这里写死，但建议通过环境变量配置：
    # api_key = "sk-xxxxxxxx"
    
    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )
    
    system_prompt = """你是一个专业的试卷信息提取Agent。
用户的输入是一段由PDF解析出来的试卷Markdown文本。
你的任务是将文本中的所有题目结构化提取出来，包括：
1. ID (id，题目的唯一标识，请使用从1开始的递增数字，或文本中原有的物理题号)
2. 题干 (question)
3. 选项 (options，如果没有选项则是空列表)
4. 答案 (answer，如果没提供则是空字符串)
5. 解析 (explanation，如果没提供则是空字符串)
6. 题型 (type，如：单选题、多选题、填空题、简答题等)
7. 是否含图(contains_pic,如果包含有图片链接，输出1，不包含图片链接，输出0)

注意：若包含图片链接，请你提取时将图片链接也提取出来。
请严格输出为一个JSON数组，不要包含任何额外的Markdown包裹（即直接输出 ```json ... ``` 内部的纯JSON代码），也不要有多余的解释。格式示例如下：
[
    {
        "id": 1,
        "type": "单选题",
        "question": "以下哪个选项是正确的？",
        "options": ["A. 选项A", "B. 选项B", "C. 选项C", "D. 选项D"],
        "answer": "A",
        "explanation": "因为A是正确的。",
        "contains_pic": 0
    }
]
"""
    
    try:
        response = client.chat.completions.create(
            model=MODEL_ZHICHUANG, # 若使用deepseek，可改为 "deepseek-chat" 或相应模型名
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请提取以下试卷内容的信息：\n\n{md_content}"}
            ],
            temperature=0.2
        )
        json_result = response.choices[0].message.content.strip()
        
        # 简单清理可能存在的markdown block
        if json_result.startswith("```json"):
            json_result = json_result[7:]
        if json_result.startswith("```"):
            json_result = json_result[3:]
        if json_result.endswith("```"):
            json_result = json_result[:-3]
            
        return json_result.strip()
    except Exception as e:
        print(f"LLM Agent 调用失败: {e}")
        return None

def main():
    pdf_path = "demo.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"错误: 找不到文件 {pdf_path}")
        return
        
    try:
        # 1. 提交PDF解析任务
        batch_id = upload_and_parse_pdf(pdf_path)
        
        # 2. 轮询等待结果并获取下载链接
        zip_url = wait_for_result(batch_id)
        
        # 3. 下载并提取MD内容
        md_content = download_and_extract_md(zip_url, extract_to="pdf_extracted")
        
        # 4. 使用 Agent 提取信息
        json_output = extract_questions_with_agent(md_content)
        
        if json_output:
            output_file = "extracted_questions.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(json_output)
            print(f"\n提取完成！结果已保存到 {output_file}")
            print(json_output[:500] + "...\n(详情请查看文件)")
            
    except Exception as e:
        print(f"执行过程中发生异常: {e}")

if __name__ == "__main__":
    main()
