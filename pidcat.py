#!/usr/bin/env -S python -u

'''
Copyright 2009, The Android Open Source Project

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

# Script to highlight adb logcat output for console
# Originally written by Jeff Sharkey, http://jsharkey.org/
# Piping detection and popen() added by other Android team members
# Package filtering and output improvements by Jake Wharton, http://jakewharton.com

import argparse
from genericpath import isfile
from pathlib import Path
from datetime import datetime
import os
import sys
import re
import subprocess
from subprocess import PIPE
import ctypes

if not (sys.version_info.major >= 3 and sys.version_info.minor >= 6):
  print('Require python version: 3.6+')
  sys.exit(-1)

__version__ = '3.0.0'

def enableVT100():
  STD_OUTPUT_HANDLE = -11
  ENABLE_VIRTUAL_TERMINAL_PROCESSING = 4
  stdout = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
  if stdout == -1:
    raise ctypes.WinError()
  mode = ctypes.c_uint()
  if ctypes.windll.kernel32.GetConsoleMode(stdout, ctypes.byref(mode)) == 0:
    raise ctypes.WinError()
  mode.value = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
  if ctypes.windll.kernel32.SetConsoleMode(stdout, mode) == 0:
    raise ctypes.WinError()

#if os.name == 'nt':
#  enableVT100()

TID_WDITH = 6

LOG_LEVELS = 'VDIWEF'
LOG_LEVELS_MAP = dict([(LOG_LEVELS[i], i) for i in range(len(LOG_LEVELS))])
parser = argparse.ArgumentParser(description='Filter logcat by package name')
parser.add_argument('package', nargs='*', help='Application package name(s)')
parser.add_argument('-w', '--tag-width', metavar='N', dest='tag_width', type=int, default=13, help='Width of log tag')
parser.add_argument('-l', '--min-level', dest='min_level', type=str, choices=LOG_LEVELS+LOG_LEVELS.lower(), default='V', help='Minimum level to be displayed')
parser.add_argument('--color-gc', dest='color_gc', action='store_true', help='Color garbage collection')
parser.add_argument('-f', '--file', type=str, help='adb raw output append to file')
parser.add_argument('-g', '--always-color', dest='always_color', action='store_true',default=False, help='If output to terminal, not corlored by default. With this option, always keep color(use for command like: pidcat | tee logfile)')
parser.add_argument('--always-display-tags', dest='always_tags', action='store_true',help='Always display the tag name')
parser.add_argument('--current', dest='current_app', action='store_true',help='Filter logcat by current running app')
parser.add_argument('-s', '--serial', dest='device_serial', help='Device serial number (adb -s option)')
parser.add_argument('-d', '--device', dest='use_device', action='store_true', help='Use first device for log input (adb -d option)')
parser.add_argument('-e', '--emulator', dest='use_emulator', action='store_true', help='Use first emulator for log input (adb -e option)')
parser.add_argument('-c', '--clear', dest='clear_logcat', action='store_true', help='Clear the entire log before running')
parser.add_argument('-t', '--tag', dest='tag', action='append', help='Filter output by specified tag(s)')
parser.add_argument('-i', '--ignore-tag', dest='ignored_tag', action='append', help='Filter output by ignoring specified tag(s)')
parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + __version__, help='Print the version number and exit')
parser.add_argument('--time', dest='time', action='store_true', default=False, help='Print time and thread')
parser.add_argument('-W', '--nolinewrap', dest='no_line_wrap', action='store_true', default=False, help='disable line wrap')
parser.add_argument('-a', '--all', dest='all', action='store_true', default=False, help='Print all log messages')
parser.add_argument('--ssh', dest='ssh', help='use ssh instead of adb')

args = parser.parse_args()
min_level = LOG_LEVELS_MAP[args.min_level.upper()]

if not args.ssh and subprocess.check_output(['adb', 'devices'], universal_newlines=True).count('device') <= 1:
  print('no android device attached')
  sys.exit(-1)

package = args.package

base_adb_command = ['adb']
if args.device_serial:
  base_adb_command.extend(['-s', args.device_serial])
elif os.path.isfile(os.path.join(Path.home(), '.android_default_device')):
  device = Path(os.path.join(Path.home(), '.android_default_device')).read_text().rstrip()
  print(f'device is {device}')
  base_adb_command.extend(['-s', device])

if args.use_device:
  base_adb_command.append('-d')
if args.use_emulator:
  base_adb_command.append('-e')

if args.ssh:
  base_adb_command = ['ssh', args.ssh]

if args.current_app:
  system_dump_command = base_adb_command + ["shell", "dumpsys", "activity", "recents"] if not args.ssh else ["dumpsys", "activity", "recents"]
  system_dump = subprocess.Popen(system_dump_command, stdout=PIPE, stderr=PIPE).communicate()[0]
  dump_str = bytes.decode(system_dump, 'utf-8')
  match_obj = re.search(r"\* Recent #0: Task.* type=([^ ]+) .*A=\d+:([a-zA-Z0-9._$-]+)", dump_str)
  if match_obj == None:
    print('screen off ? exit.')
    sys.exit(-1)
  activity_type = match_obj.group(1)
  running_package_name = match_obj.group(2)
  if activity_type != 'home':
    print(f'running package name: {running_package_name}')
    package.append(running_package_name)

if len(package) == 0:
  args.all = True

raw_file = None
if args.file:
  append = os.path.isfile(args.file)
  raw_file = open(args.file, 'a', encoding='utf-8')
  if append:
    raw_file.write('\n' * 10)
    raw_file.write('=' * 80)
    raw_file.write('\n')
  raw_file.write(datetime.strftime(datetime.now(), '%Y-%m-%d %H:%M:%S') + '\n')
  raw_file.write(' '.join(sys.argv) + '\n')
  raw_file.write('raw log: \n')
  raw_file.write('\n')

# Store the names of packages for which to match all processes.
catchall_package = list(filter(lambda package: package.find(":") == -1, package))
# Store the name of processes to match exactly.
named_processes = list(filter(lambda package: package.find(":") != -1, package))
# Convert default process names from <package>: (cli notation) to <package> (android notation) in the exact names match group.
named_processes = map(lambda package: package if package.find(":") != len(package) - 1 else package[:-1], named_processes)

fixed_header_size = args.tag_width + 1 + 3 + 1 + (TID_WDITH + 2) # space, level, space
header_size = args.tag_width + 1 + 3 + 1 + (TID_WDITH + 2) # space, level, space

stdout_isatty = sys.stdout.isatty()

width = -1
if not args.no_line_wrap:
  try:
    # Get the current terminal width
    import fcntl, termios, struct
    h, width = struct.unpack('hh', fcntl.ioctl(0, termios.TIOCGWINSZ, struct.pack('hh', 0, 0)))
  except:
    pass

BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)

RESET = '\033[0m'

def termcolor(fg=None, bg=None):
  codes = []
  if fg is not None: codes.append('3%d' % fg)
  if bg is not None: codes.append('10%d' % bg)
  return '\033[%sm' % ';'.join(codes) if codes else ''

def colorize(message, fg=None, bg=None):
  return termcolor(fg, bg) + message + RESET if stdout_isatty or args.always_color else message

def indent_wrap(message):
  if width == -1:
    return message
  message = message.replace('\t', '    ')
  wrap_area = width - header_size
  messagebuf = ''
  current = 0
  while current < len(message):
    next = min(current + wrap_area, len(message))
    messagebuf += message[current:next]
    if next < len(message):
      messagebuf += '\n'
      messagebuf += ' ' * header_size
    current = next
  return messagebuf


LAST_USED = [RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN]
KNOWN_TAGS = {
  'dalvikvm': WHITE,
  'Process': WHITE,
  'ActivityManager': WHITE,
  'ActivityThread': WHITE,
  'AndroidRuntime': CYAN,
  'jdwp': WHITE,
  'StrictMode': WHITE,
  'DEBUG': YELLOW,
}

def allocate_color(tag):
  # this will allocate a unique format for the given tag
  # since we dont have very many colors, we always keep track of the LRU
  if tag not in KNOWN_TAGS:
    KNOWN_TAGS[tag] = LAST_USED[0]
  color = KNOWN_TAGS[tag]
  if color in LAST_USED:
    LAST_USED.remove(color)
    LAST_USED.append(color)
  return color

TID_LAST_USED = [WHITE, GREEN, YELLOW, BLUE, MAGENTA, CYAN]
TID_KNOWN_LIST = {}
def allocate_tid_color(tid, is_main_tid):
  if is_main_tid:
    return RED
  if tid not in TID_KNOWN_LIST:
    TID_KNOWN_LIST[tid] = TID_LAST_USED[0]
  color = TID_KNOWN_LIST[tid]
  if color in TID_LAST_USED:
    TID_LAST_USED.remove(color)
    TID_LAST_USED.append(color)
  return color


RULES = {
  # StrictMode policy violation; ~duration=319 ms: android.os.StrictMode$StrictModeDiskWriteViolation: policy=31 violation=1
  re.compile(r'^(StrictMode policy violation)(; ~duration=)(\d+ ms)')
    : r'%s\1%s\2%s\3%s' % (termcolor(RED), RESET, termcolor(YELLOW), RESET),
}

# Only enable GC coloring if the user opted-in
if args.color_gc:
  # GC_CONCURRENT freed 3617K, 29% free 20525K/28648K, paused 4ms+5ms, total 85ms
  key = re.compile(r'^(GC_(?:CONCURRENT|FOR_M?ALLOC|EXTERNAL_ALLOC|EXPLICIT) )(freed <?\d+.)(, \d+\% free \d+./\d+., )(paused \d+ms(?:\+\d+ms)?)')
  val = r'\1%s\2%s\3%s\4%s' % (termcolor(GREEN), RESET, termcolor(YELLOW), RESET)

  RULES[key] = val


TAGTYPES = {
  'V': colorize(' V ', fg=WHITE, bg=BLACK),
  'D': colorize(' D ', fg=BLACK, bg=BLUE),
  'I': colorize(' I ', fg=BLACK, bg=GREEN),
  'W': colorize(' W ', fg=BLACK, bg=YELLOW),
  'E': colorize(' E ', fg=BLACK, bg=RED),
  'F': colorize(' F ', fg=BLACK, bg=RED),
}

PID_LINE = re.compile(r'^\w+\s+(\w+)\s+\w+\s+\w+\s+\w+\s+\w+\s+\w+\s+\w\s([\w|\.|\/]+)$')
PID_START = re.compile(r'^.*: Start proc ([a-zA-Z0-9._:]+) for ([a-z]+ [^:]+): pid=(\d+) uid=(\d+) gids=(.*)$')
PID_START_5_1 = re.compile(r'^.*: Start proc (\d+):([a-zA-Z0-9._:]+)/[a-z0-9]+ for (.*)$')
PID_START_DALVIK = re.compile(r'^E/dalvikvm\(\s*(\d+)\): >>>>> ([a-zA-Z0-9._:]+) \[ userId:0 \| appId:(\d+) \]$')
PID_KILL  = re.compile(r'^.*Killing (\d+):([a-zA-Z0-9._:]+)/[^:]+: (.*)$')
PID_LEAVE = re.compile(r'^.*No longer want ([a-zA-Z0-9._:]+) \(pid (\d+)\): .*$')
PID_DEATH = re.compile(r'^.*Process ([a-zA-Z0-9._:]+) \(pid (\d+)\) has died.?$')
LOG_LINE_PREFIX = r'^(\d+-\d+\s+\d+:\d+:\d+\.\d+)\s+(\d+)\s+(\d+)\s+?'
LOG_LINE  = re.compile(LOG_LINE_PREFIX + r'([A-Z])\s(.+?): ?(.*?)$')
BUG_LINE  = re.compile(r'.*nativeGetEnabledTags.*')
BACKTRACE_LINE = re.compile(r'^#(.*?)pc\s(.*?)$')

adb_command = base_adb_command[:]
adb_command.append('logcat')
adb_command.extend(['-v', 'threadtime'])

# Clear log before starting logcat
if args.clear_logcat:
  adb_clear_command = list(adb_command)
  adb_clear_command.append('-c')
  adb_clear = subprocess.Popen(adb_clear_command)

  while adb_clear.poll() is None:
    pass

# This is a ducktype of the subprocess.Popen object
class FakeStdinProcess():
  def __init__(self):
    self.stdout = sys.stdin
  def poll(self):
    return None

if sys.stdin.isatty():
  adb = subprocess.Popen(adb_command, stdin=PIPE, stdout=PIPE)
  # fake_cmd = ['cat', '/Users/julee/Documents/code/pidcat/logNoDisplay.txt']
  # adb = subprocess.Popen(fake_cmd, stdin=PIPE, stdout=PIPE)
else:
  adb = FakeStdinProcess()
pids = set()
last_tid = None
last_owner = None
app_pid = None
last_tag = None
tid_color_dict = {}

def match_packages(token):
  if len(package) == 0:
    return True
  if token in named_processes:
    return True
  index = token.find(':')
  return (token in catchall_package) if index == -1 else (token[:index] in catchall_package)

def parse_death(tag, message):
  if tag != 'ActivityManager':
    return None, None
  kill = PID_KILL.match(message)
  if kill:
    pid = kill.group(1)
    package_line = kill.group(2)
    if match_packages(package_line) and pid in pids:
      return pid, package_line
  leave = PID_LEAVE.match(message)
  if leave:
    pid = leave.group(2)
    package_line = leave.group(1)
    if match_packages(package_line) and pid in pids:
      return pid, package_line
  death = PID_DEATH.match(message)
  if death:
    pid = death.group(2)
    package_line = death.group(1)
    if match_packages(package_line) and pid in pids:
      return pid, package_line
  return None, None

def parse_start_proc(line):
  start = PID_START_5_1.match(line)
  if start is not None:
    line_pid, line_package, target = start.groups()
    return line_package, target, line_pid, '', ''
  start = PID_START.match(line)
  if start is not None:
    line_package, target, line_pid, line_uid, line_gids = start.groups()
    return line_package, target, line_pid, line_uid, line_gids
  start = PID_START_DALVIK.match(line)
  if start is not None:
    line_pid, line_package, line_uid = start.groups()
    return line_package, '', line_pid, line_uid, ''
  return None

def tag_in_tags_regex(tag, tags):
  return any(re.match(r'^' + t + r'$', tag) for t in map(str.strip, tags))

def padding_tid(tid: str):
  return ' ' * (TID_WDITH - len(tid)) + tid

ps_command = base_adb_command + ['shell', 'ps'] if not args.ssh else ['ps']
ps_pid = subprocess.Popen(ps_command, stdin=PIPE, stdout=PIPE, stderr=PIPE)
while True:
  try:
    line = ps_pid.stdout.readline().decode('utf-8', 'replace').strip()
  except KeyboardInterrupt:
    break
  if len(line) == 0:
    break

  pid_match = PID_LINE.match(line)
  if pid_match is not None:
    pid = pid_match.group(1)
    proc = pid_match.group(2)
    if proc in catchall_package:
      seen_pids = True
      pids.add(pid)

while adb.poll() is None:
  try:
    line = adb.stdout.readline().decode('utf-8', 'replace').strip()
  except KeyboardInterrupt:
    break
  if len(line) == 0:
    break

  bug_line = BUG_LINE.match(line)
  if bug_line is not None:
    continue

  log_line = LOG_LINE.match(line)
  if log_line is None:
    continue

  line_time, owner, tid, level, tag, message = log_line.groups()
  is_main_thread = owner == tid
  if line_time and len(line_time) > 6:
    line_time = line_time[6:]
  if line_time and args.time:
    header_size = fixed_header_size + len(line_time) + 2
  tid_str = padding_tid(tid)
  tag = tag.strip()
  start = parse_start_proc(line)
  if start:
    line_package, target, line_pid, line_uid, line_gids = start
    if match_packages(line_package):
      pids.add(line_pid)

      app_pid = line_pid

      linebuf  = '\n'
      linebuf += line_time + ' ' if args.time and line_time != None else ''
      linebuf += colorize(' ' * (header_size - 1), bg=WHITE)
      linebuf += indent_wrap(' Process %s created for %s\n' % (line_package, target))
      linebuf += colorize(' ' * (header_size - 1), bg=WHITE)
      linebuf += ' PID: %s   UID: %s   GIDs: %s' % (line_pid, line_uid, line_gids)
      linebuf += '\n'
      print(linebuf)
      last_tag = None # Ensure next log gets a tag printed
      last_tid = None # Ensure next log gets a tag printed
      last_owner = None
      tid_color_dict = {}

  dead_pid, dead_pname = parse_death(tag, message)
  if dead_pid:
    pids.remove(dead_pid)
    linebuf  = '\n'
    linebuf += colorize(' ' * (header_size - 1), bg=RED)
    linebuf += ' Process %s (PID: %s) ended' % (dead_pname, dead_pid)
    linebuf += '\n'
    print(linebuf)
    last_tag = None # Ensure next log gets a tag printed
    last_tid = None # Ensure next log gets a tag printed
    last_owner = None
    tid_color_dict = {}

  # Make sure the backtrace is printed after a native crash
  if tag == 'DEBUG':
    bt_line = BACKTRACE_LINE.match(message.lstrip())
    if bt_line is not None:
      message = message.lstrip()
      owner = app_pid

  if not args.all and owner not in pids:
    continue
  if level in LOG_LEVELS_MAP and LOG_LEVELS_MAP[level] < min_level:
    continue
  if args.ignored_tag and tag_in_tags_regex(tag, args.ignored_tag):
    continue
  if args.tag and not tag_in_tags_regex(tag, args.tag):
    continue

  linebuf = line_time + ' ' if args.time and line_time != None else ''

  if args.tag_width > 0:
    # right-align tag title and allocate color if needed
    if tag != last_tag or args.always_tags:
      last_tag = tag
      color = allocate_color(tag)
      tag = tag[-args.tag_width:].rjust(args.tag_width)
      linebuf += colorize(tag, fg=color)
    else:
      linebuf += ' ' * args.tag_width
    linebuf += ' '

  if tid != last_tid or owner != last_owner:
    last_tid = tid
    last_owner = owner
    color = allocate_tid_color(tid, is_main_thread)
    linebuf += ' ' + colorize(tid_str, fg=color) + ' '
  else:
    linebuf += ' ' + ' ' * len(tid_str) + ' '

  # write out level colored edge
  if level in TAGTYPES:
    linebuf += TAGTYPES[level]
  else:
    linebuf += ' ' + level + ' '
  linebuf += ' '

  # format tag message using rules
  for matcher in RULES:
    replace = RULES[matcher]
    message = matcher.sub(replace, message)

  linebuf += indent_wrap(message)
  print(linebuf)
  if raw_file != None:
    raw_file.write(line)
    raw_file.write('\n')
