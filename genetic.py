import pandas as pd
import numpy as np
import re

fields = ["price", "volume", "value"]


class VM:
    df: pd.DataFrame
    memory = np.zeros(256)
    stk = np.zeros(65536)
    sp = 0
    ip = 0
    halted = False
    maxexec = 5000

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

    def execute(self, code):
        steps = 0
        while not self.halted:
            op = code[self.ip]
            getattr(self, op[0])(op[1])
            self.ip += 1
            steps += 1
            if self.ip == len(code) or steps >= self.maxexec:
                break
        print("Executed instructions: ", steps)

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
        window = self.POP(0)
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.std())

    def MAX(self, value):
        assert self.sp > 0
        window = self.POP(0)
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.max())

    def MIN(self, value):
        assert self.sp > 0
        window = self.POP(0)
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.min())

    def MEDIAN(self, value):
        assert self.sp > 0
        window = self.POP(0)
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.median())

    def MEAN(self, value):
        assert self.sp > 0
        window = self.POP(0)
        df = self.df[fields[value % len(fields)]].tail(window)
        self.PUSH(df.mean())

    def ADD(self, value):
        assert self.sp > 1
        self.PUSH(self.POP(0) + self.POP(0))

    def SUB(self, value):
        assert self.sp > 1
        self.PUSH(self.POP(0) - self.POP(0))

    def MUL(self, value):
        assert self.sp > 1
        self.PUSH(self.POP(0) * self.POP(0))

    def DIV(self, value):
        assert self.sp > 1
        self.PUSH(self.POP(0) / self.POP(0))

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

    def HALT(self, value):
        self.halted = True

    def print_top(self):
        print(self.stk[self.sp - 1])


vm = VM()

vm.execute(
    vm.parse(
        """

# Load 0 to Sum
LOADK 0
STORE $Sum

# Load 10 to Target
LOADK 10
STORE $Target

# Load 0 to Index
LOADK 0
STORE $Index

# Begin loop
Loop: LOAD $Index
LOAD $Target
CMPLT
JNZ Complete

LOAD $Index

DUP
LOADK 1
ADD
STORE $Index

LOAD $Sum
ADD
STORE $Sum

JMP Loop

Complete: LOAD $Sum
"""
    )
)
vm.print_top()

print(vm.memory[0:3])
