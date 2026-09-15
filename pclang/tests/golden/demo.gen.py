# 由 pcl 0.1.0.dev0 生成，源：demo.pcl。请勿手工编辑。
from pcl.runtime import emit, text, submit, push_sink, pop_sink

SCORE = 0  # pcl:2

def main(__pcl_prompt=""):
    global prompt, SCORE, reply
    prompt = __pcl_prompt
    emit("\n")  # pcl:3
    push_sink()  # pcl:4
    __pcl_t1 = text(prompt)  # pcl:6
    emit("请就以下主题写一段话，并把自评质量分（0..10 整数）写入 SCORE：\n" + __pcl_t1 + "\n\n")  # pcl:5-7
    __pcl_buf = pop_sink()  # pcl:8
    __pcl_r = submit(__pcl_buf, writes=("SCORE",))  # pcl:8
    reply = __pcl_r.reply  # pcl:8
    if "SCORE" in __pcl_r.writes: SCORE = __pcl_r.writes["SCORE"]  # pcl:8
    emit(reply + ("\n" if __pcl_buf.endswith("\n") else ""))  # pcl:8
    if SCORE >= 7:  # pcl:8
        emit("质量达标，结束。\n")  # pcl:9
    else:  # pcl:10
        emit("分数不够，重写一遍，把新分数写入 SCORE。\n")  # pcl:11
