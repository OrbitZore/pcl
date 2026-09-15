# 由 pcl 0.1.0.dev0 生成，源：rewrite.pcl。请勿手工编辑。
from pcl.runtime import emit, text, submit, push_sink, pop_sink, save, new_ctx, __pcl_freeze

from math import floor  # pcl:1
SCORE = 0  # pcl:3
HISTORY = []  # pcl:4
def attempt(prompt=""):  # pcl:6
    push_sink()  # pcl:7
    __pcl_t1 = text(len(HISTORY) + 1)  # pcl:8
    __pcl_t2 = text(prompt)  # pcl:9
    emit("请就以下主题写一段话（第 " + __pcl_t1 + " 次尝试），完成后调用 pcl_write 把自评质量分（0..10 整数）写入 SCORE：\n" + __pcl_t2 + "\n")  # pcl:8-9
    __pcl_buf = pop_sink()  # pcl:10
    __pcl_r = submit(__pcl_buf, writes=("SCORE",))  # pcl:10
    reply = __pcl_r.reply  # pcl:10
    if "SCORE" in __pcl_r.writes: SCORE = __pcl_r.writes["SCORE"]  # pcl:10
    emit(reply + ("\n" if __pcl_buf.endswith("\n") else ""))  # pcl:10
    return (SCORE)  # pcl:10

def main(__pcl_prompt=""):
    global prompt, SCORE, _, cx, reply, s
    prompt = __pcl_prompt
    emit("\n\n\n")  # pcl:2-12
    cx = save()  # pcl:13
    while SCORE < 7 and len(HISTORY) < 5:  # pcl:14
        SCORE = attempt(prompt)  # pcl:15
        _ = HISTORY.append(SCORE)  # pcl:16
    emit("\n历史得分：\n")  # pcl:18-19
    for s in HISTORY:  # pcl:20
        __pcl_t1 = text(s)  # pcl:21
        emit("- " + __pcl_t1 + "\n")  # pcl:21
    __pcl_t2 = text(floor(sum(HISTORY) / len(HISTORY)))  # pcl:23
    emit("平均（去尾）：" + __pcl_t2 + "\n\n")  # pcl:23-24
    new_ctx()  # pcl:26
    __pcl_reads = {"HISTORY": __pcl_freeze(HISTORY)}  # pcl:27
    push_sink()  # pcl:27
    emit("请把当前得分历史总结成一句话；数据请调用 pcl_read 读取 HISTORY。\n")  # pcl:28
    __pcl_buf = pop_sink()  # pcl:27
    __pcl_r = submit(__pcl_buf, reads=__pcl_reads)  # pcl:27
    reply = __pcl_r.reply  # pcl:27
    emit(reply + ("\n" if __pcl_buf.endswith("\n") else ""))  # pcl:27
