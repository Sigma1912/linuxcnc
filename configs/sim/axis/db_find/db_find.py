#!/usr/bin/python
import os,sys

# Simulation for a [RS274NGC]DB_FIND program
# tool number range:
toolno_min = 10
toolno_max = 19

#----------------------------------------------------------------------
def startup_ack():
    if (len(sys.argv) >1):
        sys.stdout.write("ACK %s\n"%sys.argv[1])
    else:
        sys.stdout.write("NAK no argv[1]\n")
    sys.stdout.flush()

#----------------------------------------------------------------------
# Simulate db queries
def is_valid_toolno(toolno):
    global toolno_min
    global toolno_max
    if (toolno == 0): return True
    if (toolno_min <= toolno) and (toolno <= toolno_max): return True
    return False

ct = 0
def get_tool(toolno):
    global ct
    ct = ct + 1
    #note: db comments are not retained in LinuxCNC
    if toolno == 12: return "T12 P12 z.4 ; special"
    if toolno == 0: return "T0 P0 ; no tool"
    return "T%d P%d Z0.0%d D0.%d ; db entry #%d"\
           %(toolno,toolno,toolno,toolno,ct)

#----------------------------------------------------------------------
def main_loop():
    while True:
        try:
            line=sys.stdin.readline().strip().split()
        except Exception as e:
            sys.stdout.write("NAK exception=",e)

        try:
            toolno = int(line[0])
        except Exception as e:
            sys.stdout.write("NAK %s non-integer\n"%toolno)
            sys.stdout.flush()
            continue

        if not is_valid_toolno(toolno):
            sys.stdout.write("NAK %d out-of-range\n"%toolno)
            sys.stdout.flush()
            continue

        sys.stdout.write(get_tool(toolno)+"\n")
        sys.stdout.flush()
#----------------------------------------------------------------------
try:
    startup_ack()
    main_loop()
except Exception as e:
    if sys.stdin.isatty():
        print("exception=",e)
    else: pass # avoid messages at termination
