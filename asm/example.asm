        JMP Main

FnSum:  STORE $Target
        LOAD0
        STORE $Sum
        LOAD0
        STORE $Index

FnLoop: LOAD $Index
        LOAD $Target
        CMPLT
        JNZ FnDone

        LOAD $Index

        DUP
        LOAD1
        ADD
        STORE $Index

        LOAD $Sum
        ADD
        STORE $Sum

        JMP FnLoop

FnDone: LOAD $Sum
        RET

Main:   PUSH 10
        CALL FnSum
        PRINT
        PUSH 100
        CALL FnSum
        PRINT