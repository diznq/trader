from typing import Optional, Union
import pandas as pd
import numpy as np
import re
import random

fields = ["price", "volume", "value"]


class VM:
    df: pd.DataFrame
    memory = np.zeros(256)
    stk = np.zeros(65536)
    call_stk = np.zeros(65536, dtype=np.uint32)
    sp = 0
    csp = 0
    ip = 0
    steps = 0
    ccy = 1000
    crypto = 0
    halted = False
    exceeded = False
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

    def reset(self):
        self.steps = 0
        self.ip = 0
        self.sp = 0
        self.csp = 0
        self.halted = False
        self.exceeded = True
        self.ccy = 1000
        self.crypto = 0
        self.memory = np.zeros(256)
        self.stk = np.zeros(65536)
        self.call_stk = np.zeros(65536, dtype=np.uint32)

    def execute(self, code) -> float:
        self.reset()
        while not self.halted:
            op = code[self.ip]
            getattr(self, op[0])(op[1])
            self.ip += 1
            self.steps += 1
            if self.ip == len(code) or self.steps >= self.maxexec:
                self.exceeded = self.steps >= self.maxexec
                break

        if self.sp <= 0:
            return None
        return self.stk[self.sp - 1]

    def PUSH(self, value: Union[int, float]):
        self.stk[self.sp] = value
        self.sp += 1

    def POP(self, value: Optional[int] = None):
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

    def DUP(self, value: Optional[int]):
        assert self.sp > 0
        self.PUSH(self.stk[self.sp - 1])

    def DUP2(self, value: Optional[int]):
        assert self.sp > 1
        b = self.POP(0)
        a = self.POP(0)
        self.PUSH(a)
        self.PUSH(b)
        self.PUSH(a)
        self.PUSH(b)

    def STD(self, value: int):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.std())

    def MAX(self, value: int):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.max())

    def MIN(self, value: int):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.min())

    def MEDIAN(self, value: int):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.median())

    def MEAN(self, value: int):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.mean())

    def READ(self, value: int):
        assert self.sp > 0
        window = int(self.POP(0))
        df = self.df[fields[value % len(fields)]].tail(window).head(1)
        if df.shape[0] == 0:
            self.PUSH(0)
        else:
            self.PUSH(df.values[0])

    def ADD(self, value: Optional[int] = None):
        assert self.sp > 1
        self.PUSH(self.POP(0) + self.POP(0))

    def SUB(self, value: Optional[int] = None):
        assert self.sp > 1
        b = self.POP(0)
        a = self.POP(0)
        self.PUSH(a - b)

    def MUL(self, value: Optional[int] = None):
        assert self.sp > 1
        self.PUSH(self.POP(0) * self.POP(0))

    def DIV(self, value: Optional[int] = None):
        assert self.sp > 1
        b = self.POP(0)
        a = self.POP(0)
        assert b != 0
        self.PUSH(a / b)

    def MOD(self, value: Optional[int] = None):
        assert self.sp > 1
        b = self.POP(0)
        a = self.POP(0)
        assert b != 0
        self.PUSH(a % b)

    def CMPEQ(self, value: Optional[int] = None):
        assert self.sp > 1
        self.PUSH(0 if self.POP(0) == self.POP(0) else 1)

    def CMPLT(self, value: Optional[int] = None):
        assert self.sp > 1
        self.PUSH(0 if self.POP(0) >= self.POP(0) else 1)

    def CMPLTE(self, value: Optional[int] = None):
        assert self.sp > 1
        self.PUSH(0 if self.POP(0) > self.POP(0) else 1)

    def JZ(self, value: int):
        assert self.sp > 0
        if self.POP(0) == 0:
            self.ip += value - 1

    def JNZ(self, value: int):
        assert self.sp > 0
        if self.POP(0) != 0:
            self.ip += value - 1

    def JMP(self, value: int):
        self.ip += value - 1

    def CALL(self, value: int):
        self.call_stk[self.csp] = self.ip
        self.csp += 1
        self.ip += value - 1

    def RET(self, value: Optional[int] = None):
        assert self.csp > 0
        self.csp -= 1
        self.ip = self.call_stk[self.csp]

    def HALT(self, value: Optional[int] = None):
        self.halted = True

    def PRINT(self, value: Optional[int] = None):
        assert self.sp > 0
        print(self.stk[self.sp - 1])

    def BUY(self, value: Optional[int] = None):
        price = self.df["price"].tail(1)[0]
        amt = self.ccy / price
        self.ccy -= amt * price
        self.crypto += amt

    def SELL(self, value: Optional[int] = None):
        price = self.df["price"].tail(1)[0]
        self.ccy += self.crypto * price
        self.crypto = 0

    def get_is(self):
        censored = ["PRINT", "HALT", "PUSH", "POP"]
        return [fn for fn in dir(VM) if fn == fn.upper() and fn not in censored]

    def print_top(self):
        print(self.stk[self.sp - 1])

    def equity(self):
        price = self.df["price"].tail(1)[0]
        return self.ccy + self.crypto * price

base = pd.read_csv(
    "stock_dataset.csv",
    header=None,
    names=["seq", "symbol", "price", "bid", "ask", "side", "time", "txid", "vol"],
    parse_dates=["time"],
).set_index("time")


for j in range(0, 200000):
    vm = VM(base.head(1000))
    isa = vm.get_is()
    df = base.tail(-1000).head(1000)
    code = [ [random.choice(isa), random.randint(0, 50)] for x in range(0, 20) ]
    # print(code)
    interrupted = False
    for i in range(0, df.shape[0]):
        row = df.head(i).tail(1)
        vm.on_row(row)
        try:
            result = vm.execute(code)
        except BaseException as ex:
            #print("Steps: ", vm.steps)
            interrupted = True
            break
    
    if not interrupted:
        print(vm.equity(), code)

print(vm.get_is())