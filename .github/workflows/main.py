import sqlite3
import requests
import os
import cv2
import base64
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.lang import Builder
from kivy.core.text import LabelBase
from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.graphics.texture import Texture

# ============ 注册Windows黑体，解决中文方框问题 ============
try:
    LabelBase.register(name="SimHei", fn_regular="C:/Windows/Fonts/simhei.ttf")
except:
    try:
        LabelBase.register(name="MicrosoftYaHei", fn_regular="C:/Windows/Fonts/msyh.ttc")
    except:
        pass

# ===================== 千问API配置 =====================
DASHSCOPE_API_KEY = "sk-sp-H.DEEPMY.yL8q.MEUCIQDjQBLcuFu737V63me2ILOniw0269FdPh0xLYZk1c-ilwIgbT9XAFnqMJ2xYT0zdcffdFgx0jtkAHrJyjs6sS92y88"
QWEN_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
QWEN_MODEL = "qwen3.7-plus"
QWEN_VL_MODEL = "qwen-vl-plus" # 修复相机OCR缺失变量
# 初始化数据库
def init_db():
    conn = sqlite3.connect('error_questions.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            question TEXT,
            answer TEXT,
            wrong_reason TEXT,
            category TEXT,
            difficulty TEXT,
            is_star INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 追加字段，旧库兼容
    try:
        cursor.execute("ALTER TABLE questions ADD COLUMN difficulty TEXT")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE questions ADD COLUMN is_star INTEGER DEFAULT 0")
    except:
        pass
    conn.commit()
    conn.close()

# 调用千问生成举一反三
def qwen_generate_extend(question, category, subject):
    prompt = f"""
学段学科：{subject}
知识点：{category}
题目：{question}
自动生成举一反三变式练习题。
要求：输出2道同类型变式题，附带答案+简要解析，难度匹配学段。
"""
    headers = {"Authorization": f"Bearer {API_KEY}"}
    data = {
        "model": "qwen-turbo",
        "input": {"messages": [{"role": "user", "content": prompt}]}
    }
    try:
        resp = requests.post(QWEN_URL, headers=headers, json=data, timeout=20)
        if resp.status_code == 200:
            return resp.json()["output"]["text"]
        else:
            return "AI生成失败：API返回错误"
    except Exception as e:
        return f"AI调用异常：{str(e)}"

# AI智能重点复习：读取该学科全部错题，自动分析薄弱点，生成复习方案
def qwen_ai_review(subject, all_error_text):
    prompt = f"""
【学段学科】{subject}
下面是该学科所有错题、知识点和错因：
{all_error_text}

任务：
1. 自动统计高频薄弱知识点，列出优先级（哪些是最大短板）
2. 总结共性错误原因
3. 输出重点复习提纲
4. 生成3道针对性强化练习题，附带答案解析，难度匹配该学段
输出格式清晰易懂，适合学生复习。
"""
    headers = {"Authorization": f"Bearer {API_KEY}"}
    data = {
        "model": "qwen-turbo",
        "input": {"messages": [{"role": "user", "content": prompt}]}
    }
    try:
        resp = requests.post(QWEN_URL, headers=headers, json=data, timeout=30)
        if resp.status_code == 200:
            return resp.json()["output"]["text"]
        else:
            return "AI智能复习失败：API返回错误"
    except Exception as e:
        return f"AI调用异常：{str(e)}"

# 图片转base64 + 千问OCR识别拍照图片
def ocr_image(img_path):
    with open(img_path, "rb") as f:
        img_bytes = f.read()
    img_base64 = base64.b64encode(img_bytes).decode("utf-8")
    headers = {"Authorization": f"Bearer {API_KEY}"}
    data = {
        "model": "qwen-ocr",
        "input": {"image": f"data:image/jpeg;base64,{img_base64}"}
    }
    try:
        resp = requests.post(OCR_URL, headers=headers, json=data, timeout=30)
        if resp.status_code == 200:
            return resp.json()["output"]["text"]
        else:
            return f"OCR识别失败，code:{resp.status_code}"
    except Exception as e:
        return f"OCR异常：{str(e)}"

# 批量导入错题txt文件，格式规范：一行一题，用||分割 学科||题目||答案||错因||知识点||难度
def import_questions_from_txt(filepath):
    count = 0
    conn = sqlite3.connect('error_questions.db')
    cur = conn.cursor()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("||")
            if len(parts)>=6:
                subj,q,a,wr,cat,diff = parts[:6]
                cur.execute('''
                    INSERT INTO questions (subject, question, answer, wrong_reason, category, difficulty, is_star)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                ''',(subj.strip(),q.strip(),a.strip(),wr.strip(),cat.strip(),diff.strip()))
                count +=1
        conn.commit()
    except Exception as e:
        return f"导入失败：{str(e)}，成功{count}条"
    conn.close()
    return f"✅导入完成，共读取 {count} 条错题"

# 页面类定义
class AddPage(Screen):
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.capture = None
        self.camera_running = False

    def start_camera(self):
        if not self.camera_running:
            self.capture = cv2.VideoCapture(0)
            self.camera_running = True
            Clock.schedule_interval(self.update_camera_frame, 1/30)

    def stop_camera(self):
        if self.camera_running and self.capture:
            self.capture.release()
            self.camera_running = False
            Clock.unschedule(self.update_camera_frame)

    def update_camera_frame(self, dt):
        ret, frame = self.capture.read()
        if ret:
            buf = cv2.flip(frame,0).tobytes()
            img_texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='bgr')
            img_texture.blit_buffer(buf, colorfmt='bgr', bufferfmt='ubyte')
            self.ids.cam_display.texture = img_texture

    # 拍照OCR
    def take_photo_and_ocr(self):
        if not self.capture:
            self.ids.msg.text = "⚠️请先启动摄像头！"
            return
        ret, frame = self.capture.read()
        img_path = "ocr_temp.jpg"
        cv2.imwrite(img_path, frame)
        self.ids.msg.text = "📸图片已拍摄，正在OCR识别..."
        res_text = ocr_image(img_path)
        self.ids.in_question.text = res_text
        self.ids.msg.text = "✅OCR识别完成，请核对题目！"

    # 导入txt错题
    def import_txt_file(self):
        fname = "import_question.txt"
        if os.path.exists(fname):
            ret = import_questions_from_txt(fname)
            self.ids.msg.text = ret
        else:
            self.ids.msg.text = "❌找不到 import_question.txt，请放在程序同目录！"

    # 保存错题
    def on_save_question(self):
        subj_in = self.ids.get("in_subject")
        q_in = self.ids.get("in_question")
        ans_in = self.ids.get("in_answer")
        reason_in = self.ids.get("in_wrongreason")
        cat_in = self.ids.get("in_category")
        diff_sp = self.ids.get("sp_difficulty")
        msg_label = self.ids.get("msg")
        out_extend = self.ids.get("out_extend")

        subject = subj_in.text.strip() if subj_in else ""
        question = q_in.text.strip() if q_in else ""
        answer = ans_in.text.strip() if ans_in else ""
        wrong_reason = reason_in.text.strip() if reason_in else ""
        category = cat_in.text.strip() if cat_in else ""
        difficulty = diff_sp.text if diff_sp else "中等"

        if not all([subject, question, answer, category]):
            msg_label.text = "⚠️ 学科、题目、答案、知识点不能为空！"
            return

        conn = sqlite3.connect('error_questions.db')
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO questions (subject, question, answer, wrong_reason, category, difficulty, is_star)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        ''', (subject, question, answer, wrong_reason, category, difficulty))
        conn.commit()
        conn.close()
        msg_label.text = "✅ 题目保存成功！自动生成举一反三题目..."

        ai_result = qwen_generate_extend(question, category, subject)
        out_extend.text = ai_result

        # 清空输入框
        subj_in.text = ""
        q_in.text = ""
        ans_in.text = ""
        reason_in.text = ""
        cat_in.text = ""

class ViewScreen(Screen):
    def load_all_questions(self):
        txt = "====全部错题====\n"
        conn = sqlite3.connect("error_questions.db")
        cur = conn.cursor()
        cur.execute("SELECT id,subject,question,answer,wrong_reason,category,difficulty,is_star FROM questions")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            self.ids.out_all.text = "暂无错题记录"
            return
        for qid,sub,q,a,wr,cat,diff,star in rows:
            star_text = "⭐收藏" if star ==1 else ""
            txt += f"\nID:{qid} {star_text}\n【学科】{sub}【难度】{diff}\n【知识点】{cat}\n【题目】{q}\n【答案】{a}\n【错因】{wr}\n------------------------\n"
        self.ids.out_all.text = txt

    def export_to_txt(self):
        conn = sqlite3.connect("error_questions.db")
        cur = conn.cursor()
        cur.execute("SELECT id,subject,question,answer,wrong_reason,category,difficulty,is_star FROM questions")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            self.ids.out_all.text = "暂无错题，无法导出！"
            return
        with open("错题导出.txt","w",encoding="utf-8") as f:
            f.write("=======错题本导出=======\n")
            for qid,sub,q,a,wr,cat,diff,star in rows:
                star_text = "⭐收藏" if star ==1 else ""
                f.write(f"\nID:{qid} {star_text}\n【学科】{sub}【难度】{diff}\n【知识点】{cat}\n【题目】{q}\n【答案】{a}\n【错因】{wr}\n------------------------\n")
        self.ids.out_all.text = "✅ 导出成功！文件：错题导出.txt"

    def star_toggle(self):
        input_id = self.ids.get("input_star_id")
        if not input_id:
            return
        try:
            qid = int(input_id.text.strip())
        except:
            self.ids.out_all.text = "❌ ID必须是数字！"
            return
        conn = sqlite3.connect("error_questions.db")
        cur = conn.cursor()
        cur.execute("SELECT is_star FROM questions WHERE id=?",(qid,))
        res = cur.fetchone()
        if not res:
            self.ids.out_all.text = "❌ 找不到该ID题目"
            conn.close()
            return
        new_star = 0 if res[0]==1 else 1
        cur.execute("UPDATE questions SET is_star=? WHERE id=?",(new_star,qid))
        conn.commit()
        conn.close()
        self.ids.out_all.text = "✅ 收藏状态已切换，请重新加载错题查看！"

class WeakScreen(Screen):
    def load_weak_list(self):
        sp = self.ids.get('sp_subj')
        if not sp:
            subject = ""
        else:
            subject = sp.text
        label_weak = self.ids.get("label_weak")
        if not subject:
            label_weak.text = "请先选择学科"
            return

        import sqlite3
        conn = sqlite3.connect("error_questions.db")
        cur = conn.cursor()
        cur.execute("SELECT category,COUNT(*) FROM questions WHERE subject=? GROUP BY category",(subject,))
        rows = cur.fetchall()
        conn.close()

        if len(rows)==0:
            label_weak.text = "该学科暂无错题"
            return
        text_out = "知识点错题统计：\n"
        for cat, cnt in rows:
            text_out += f"{cat} ：{cnt}道\n"
        label_weak.text = text_out

    def review_knowledge(self):
        know_input = self.ids.get("in_know")
        out_practice = self.ids.get("out_practice")
        if not know_input:
            out_practice.text = "找不到输入框"
            return
        know_text = know_input.text.strip()
        if not know_text:
            out_practice.text = "请输入知识点名称！"
            return
        
        import sqlite3
        conn = sqlite3.connect("error_questions.db")
        cur = conn.cursor()
        cur.execute("SELECT id,subject,question,answer,wrong_reason,difficulty,is_star FROM questions WHERE category=?",(know_text,))
        rows = cur.fetchall()
        conn.close()
        
        if len(rows)==0:
            out_practice.text = "该知识点暂无错题记录"
            return
        
        txt = f"====知识点【{know_text}】错题列表====\n"
        for qid,subj,q,a,wr,diff,star in rows:
            star_text = "⭐收藏" if star ==1 else ""
            txt += f"\nID:{qid} {star_text}\n【学科】{subj}【难度】{diff}\n【题目】{q}\n【答案】{a}\n【错因】{wr}\n---------"
        out_practice.text = txt

    # ==========【新增AI智能重点复习】==========
    def ai_intelligent_review(self):
        sp = self.ids.sp_subj
        subject = sp.text
        out_practice = self.ids.out_practice
        if subject == "选择学科":
            out_practice.text = "⚠️请先选择学科！"
            return
        out_practice.text = "🔍正在读取错题，AI分析薄弱点，请稍候..."
        import sqlite3
        conn = sqlite3.connect("error_questions.db")
        cur = conn.cursor()
        cur.execute("SELECT question,answer,wrong_reason,category FROM questions WHERE subject=?",(subject,))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            out_practice.text = "❌该学科暂无错题，无法进行AI智能复习！"
            return
        # 整理全部错题文本给AI
        error_text = ""
        for q,a,wr,cat in rows:
            error_text += f"知识点:{cat}，题目:{q}，答案:{a}，错因:{wr}\n"
        # 调用AI生成复习方案
        ai_result = qwen_ai_review(subject, error_text)
        out_practice.text = ai_result

# 页面管理器
class MyScreenManager(ScreenManager):
    pass

# KV界面代码
KV_CODE = '''
<MyScreenManager>:
    AddPage:
    ViewScreen:
    WeakScreen:

<AddPage>:
    name: "add"
    BoxLayout:
        orientation: "vertical"
        padding: 10
        spacing: 8
        Label:
            text: "📝 添加错题页面（OpenCV拍照OCR识别）"
            font_name: "SimHei"
            size_hint_y:0.04
        Image:
            id: cam_display
            size_hint_y:0.22
        BoxLayout:
            size_hint_y:0.06
            spacing:10
            Button:
                text: "▶启动摄像头"
                on_press: root.start_camera()
                font_name: "SimHei"
            Button:
                text: "📷拍照识别错题"
                on_press: root.take_photo_and_ocr()
                font_name: "SimHei"
            Button:
                text: "📥导入txt错题"
                on_press: root.import_txt_file()
                font_name: "SimHei"
        BoxLayout:
            size_hint_y: 0.06
            Spinner:
                id: in_subject
                text: "选择学科"
                values: ["小学语文","小学数学","小学英语","初中语文","初中数学","初中英语","初中物理","初中化学","初中生物","初中地理","初中历史","初中道法","高中语文","高中数学","高中英语","高中物理","高中化学","高中生物","高中地理","高中历史","高中政治"]
                font_name: "SimHei"
            Spinner:
                id: sp_difficulty
                text: "中等"
                values: ["简单","中等","困难"]
                font_name: "SimHei"
        BoxLayout:
            size_hint_y: 0.06
            TextInput:
                id: in_category
                hint_text: "知识点（例如：一元二次方程）"
                font_name: "SimHei"
        TextInput:
            id: in_question
            size_hint_y: 0.14
            hint_text: "粘贴题目（拍照OCR会自动填入这里）"
            font_name: "SimHei"
        TextInput:
            id: in_answer
            size_hint_y: 0.10
            hint_text: "正确答案"
            font_name: "SimHei"
        TextInput:
            id: in_wrongreason
            size_hint_y: 0.10
            hint_text: "错误原因"
            font_name: "SimHei"
        Button:
            text: "保存错题并自动生成举一反三"
            on_press: root.on_save_question()
            font_name: "SimHei"
            size_hint_y:0.06
        Label:
            id: msg
            size_hint_y: 0.04
            color: 0,1,0,1
            font_name: "SimHei"
        ScrollView:
            size_hint_y: 0.14
            Label:
                id: out_extend
                size_hint_y: None
                height: self.texture_size[1]
                text: "AI举一反三拓展题会在这里自动显示"
                font_name: "SimHei"
        BoxLayout:
            size_hint_y: 0.06
            Button:
                text: "查看全部错题"
                on_press: app.root.current="view"
                font_name: "SimHei"
            Button:
                text: "AI智能重点复习"
                on_press: app.root.current="weak"
                font_name: "SimHei"

<ViewScreen>:
    name: "view"
    BoxLayout:
        orientation: "vertical"
        padding: 10
        spacing:8
        Label:
            text: "📖 全部错题"
            font_name: "SimHei"
            size_hint_y:0.04
        BoxLayout:
            size_hint_y:0.06
            TextInput:
                id: input_star_id
                hint_text:"输入题目ID切换收藏⭐"
                font_name: "SimHei"
            Button:
                text:"切换收藏"
                on_press:root.star_toggle()
                font_name: "SimHei"
            Button:
                text:"导出全部(TXT)"
                on_press:root.export_to_txt()
                font_name: "SimHei"
        ScrollView:
            size_hint_y: 0.74
            Label:
                id: out_all
                size_hint_y: None
                height: self.texture_size[1]
                text: "点击加载查看错题"
                font_name: "SimHei"
        BoxLayout:
            size_hint_y: 0.06
            Button:
                text: "加载全部错题"
                on_press: root.load_all_questions()
                font_name: "SimHei"
            Button:
                text: "返回添加"
                on_press: app.root.current="add"
                font_name: "SimHei"

<WeakScreen>:
    name: "weak"
    BoxLayout:
        orientation: "vertical"
        padding:10
        spacing:8
        Label:
            text: "🤖 AI智能重点复习"
            font_name: "SimHei"
            size_hint_y:0.04
        BoxLayout:
            size_hint_y: 0.06
            Spinner:
                id: sp_subj
                text: "选择学科"
                values: ["小学语文","小学数学","小学英语","初中语文","初中数学","初中英语","初中物理","初中化学","初中生物","初中地理","初中历史","初中道法","高中语文","高中数学","高中英语","高中物理","高中化学","高中生物","高中地理","高中历史","高中政治"]
                font_name: "SimHei"
            Button:
                text: "查看知识点统计"
                on_press: root.load_weak_list()
                font_name: "SimHei"
            Button:
                text: "🤖 AI智能重点复习"
                on_press: root.ai_intelligent_review()
                font_name: "SimHei"
        Label:
            id: label_weak
            size_hint_y: 0.08
            text: "统计结果"
            font_name: "SimHei"
        BoxLayout:
            size_hint_y: 0.06
            TextInput:
                id: in_know
                hint_text: "输入知识点名称，单独查看该知识点错题"
                font_name: "SimHei"
        BoxLayout:
            size_hint_y: 0.06
            Button:
                text: "查看该知识点错题"
                on_press: root.review_knowledge()
                font_name: "SimHei"
        ScrollView:
            size_hint_y: 0.56
            Label:
                id: out_practice
                size_hint_y: None
                height: self.texture_size[1]
                text: "AI智能复习结果展示区域"
                font_name: "SimHei"
        Button:
            size_hint_y: 0.06
            text: "返回添加错题"
            on_press: app.root.current="add"
            font_name: "SimHei"
'''

class ErrorNoteApp(App):
    def build(self):
        Builder.load_string(KV_CODE)
        init_db()
        return MyScreenManager()

    def on_stop(self):
        # 关闭程序时释放摄像头
        screen = self.root.get_screen("add")
        screen.stop_camera()

if __name__ == "__main__":
    ErrorNoteApp().run()
