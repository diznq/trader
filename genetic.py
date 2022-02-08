import pandas as pd
import numpy as np
import re

fields = ["price", "volume", "value"]


class VM:
    df: pd.DataFrame
    memory = np.zeros(256)
    stk = np.zeros(65536)
    call_stk = np.zeros(65536, dtype=np.uint32)
    sp = 0
    csp = 0
    ip = 0
    halted = False
    maxexec = 5000

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    def parse(self, text):
        lines = text.split("\n")
        code = []
        labels = dict()
        consts = dict()
        ctr = 0
        for line in lines:
            line = re.sub("#.*$", "", line).strip()
            if len(line) == 0:
                continue
            parts = re.match(
                "([a-zA-Z0-9_.]+:)?\\s*([a-zA-Z01]+)\\s*(\\$?[a-zA-Z0-9_.]+)?", line
            )
            if parts is None:
                continue

            label = parts[1]
            op = parts[2].upper()
            imm = parts[3]

            if label is not None:
                label = label.replace(":", "")

            # print(line, [label, op, imm])
            if imm is not None:
                if imm.startswith("$"):
                    id = 0
                    if imm in consts:
                        id = consts[imm]
                    else:
                        consts[imm] = ctr
                        id = ctr
                        ctr += 1
                    imm = id
                elif re.match("^([0-9.]+)$", imm):
                    if "." in imm:
                        imm = float(imm)
                    else:
                        imm = int(imm)
            else:
                imm = 0

            if getattr(self, op, None) is None:
                raise RuntimeError("invalid instruction: " + op)

            if label is not None:
                labels[label] = len(code)

            code.append([op, imm, label])
        final = []

        for i, inst in enumerate(code):
            if isinstance(inst[1], str):
                label = inst[1]
                if label not in labels:
                    raise RuntimeError("invalid label: " + label)
                final.append([inst[0], labels[label] - i])
            else:
                final.append([inst[0], inst[1]])

        return final

    def on_row(self, row) -> float:
        self.df = self.df.append(row)

    def execute(self, code) -> float:
        steps = 0
        self.ip = 0
        self.sp = 0
        self.csp = 0
        self.halted = False
        while not self.halted:
            op = code[self.ip]
            getattr(self, op[0])(op[1])
            self.ip += 1
            steps += 1
            if self.ip == len(code) or steps >= self.maxexec:
                break

        if self.sp <= 0:
            return None
        return self.stk[self.sp - 1]

    def PUSH(self, value):
        self.stk[self.sp] = value
        self.sp += 1

    def POP(self, value):
        assert self.sp > 0
        self.sp -= 1
        return self.stk[self.sp]

    def LOADK(self, k: int):
        self.PUSH(k)

    def LOAD0(self, k: int):
        self.PUSH(0)

    def LOAD1(self, k: int):
        self.PUSH(1)

    def LOADM1(self, k: int):
        self.PUSH(-1)

    def LOAD(self, imm: int):
        self.PUSH(self.memory[imm])

    def STORE(self, imm: int):
        self.memory[imm] = self.POP(0)

    def DUP(self, value):
        assert self.sp > 0
        self.PUSH(self.stk[self.sp - 1])

    def DUP2(self, value):
        assert self.sp > 1
        b = self.POP(0)
        a = self.POP(0)
        self.PUSH(a)
        self.PUSH(b)
        self.PUSH(a)
        self.PUSH(b)

    def STD(self, value):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.std())

    def MAX(self, value):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.max())

    def MIN(self, value):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.min())

    def MEDIAN(self, value):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.median())

    def MEAN(self, value):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.mean())

    def READ(self, value):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window).head(1)
        if df.shape[0] == 0:
            self.PUSH(0)
        else:
            self.PUSH(df.values[0])

    def ADD(self, value):
        assert self.sp > 1
        self.PUSH(self.POP(0) + self.POP(0))

    def SUB(self, value):
        assert self.sp > 1
        b = self.POP(0)
        a = self.POP(0)
        self.PUSH(a - b)

    def MUL(self, value):
        assert self.sp > 1
        self.PUSH(self.POP(0) * self.POP(0))

    def DIV(self, value):
        assert self.sp > 1
        b = self.POP(0)
        a = self.POP(0)
        self.PUSH(a / b)

    def MOD(self, value):
        assert self.sp > 1
        self.PUSH(self.POP(0) % self.POP(0))

    def CMPEQ(self, value):
        assert self.sp > 1
        self.PUSH(0 if self.POP(0) == self.POP(0) else 1)

    def CMPLT(self, value):
        assert self.sp > 1
        self.PUSH(0 if self.POP(0) >= self.POP(0) else 1)

    def CMPLTE(self, value):
        assert self.sp > 1
        self.PUSH(0 if self.POP(0) > self.POP(0) else 1)

    def JZ(self, value):
        assert self.sp > 0
        if self.POP(0) == 0:
            self.ip += value - 1

    def JNZ(self, value):
        assert self.sp > 0
        if self.POP(0) != 0:
            self.ip += value - 1

    def JMP(self, value):
        self.ip += value - 1

    def CALL(self, value):
        self.call_stk[self.csp] = self.ip
        self.csp += 1
        self.ip += value - 1

    def RET(self, value):
        assert self.csp > 0
        self.csp -= 1
        self.ip = self.call_stk[self.csp]

    def HALT(self, value):
        self.halted = True

    def PRINT(self, value):
        assert self.sp > 0
        print(self.stk[self.sp - 1])

    def print_top(self):
        print(self.stk[self.sp - 1])

base = pd.read_csv(
    "stock_dataset.csv",
    header=None,
    names=["seq", "symbol", "price", "bid", "ask", "side", "time", "txid", "vol"],
    parse_dates=["time"],
).set_index("time")

vm = VM(base.head(1000))
df = base.tail(-1000).head(10000)
for i in range(1, df.shape[0]):
    row = df.head(i).tail(1)
    vm.on_row(row)
    vm.execute(vm.parse("""
LOADK 1
READ 0
STORE $Current

LOADK 200
MAX
STORE $Max200

LOAD $Current
LOAD $Max200
DIV

DUP
LOADK 0.99
CMPLT
JNZ End

PRINT

End: HALT

"""))