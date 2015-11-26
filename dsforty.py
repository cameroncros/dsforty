#!/usr/bin/env python
# dsforty.py - Scan a page on Epson DS-40
# Copyright 2015 (C) Mansour Behabadi <mansour@oxplot.com>

from subprocess import Popen, PIPE
from collections import deque
import argparse
import atexit
import os
import sys
import tempfile
import usb.core
import usb.util

IN_BUF_SIZE = 1024 ** 2
VENDOR = 0x04b8
PRODUCT = 0x0152
EP_OUT = 0x02
EP_IN = 0x81
MAX_W = 8.5 # in inches
MAX_H = 14 # in inches

CLRS = {'g': b'M008', 'c': b'C024'}
BLANKS = {'g': 45, 'c': (44, 45, 45)}
BLANK_VARI = 25
MIN_HFEATURE_LEN = 0.3937 # in inches ~ 1mm

def find_edge(line, blank, vari, streak_thresh):
  streak = 0
  low = [max(0, c - vari) for c in blank]
  high = [min(255, c + vari) for c in blank]
  for pi, p in enumerate(line):
    for c, cl, ch in zip(p, low, high):
      if c < cl or c > ch:
        streak += 1
        if streak > streak_thresh:
          return pi - streak + 1
        break
      streak = 0
  return 0

def main():
  def arg_range(low, high):
    def fn(v):
      v = int(v)
      if v < low or v > high:
        raise argparse.ArgumentTypeError(
          'must be in range %d..%d' % (low, high))
      return v
    return fn
  parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description='Scan a page on Epson DS-40'
  )
  parser.add_argument(
    '-r', '--res',
    choices=[300, 600],
    default=300,
    type=int,
    help='scan resolution - defaults to 300 dpi'
  )
  parser.add_argument(
    '-c', '--color',
    choices=list(sorted(CLRS)),
    default='c',
    help='scan color: `g` for grayscale and `c` for color'
         ' - defaults to color'
  )
  parser.add_argument(
    '-q', '--quality',
    type=arg_range(1, 100),
    default=100,
    help='quality of output JPEG, between 1..100 - defaults to 100'
  )
  parser.add_argument(
    '-n', '--no-crop',
    action='store_true',
    help='do not crop vertical borders - use when autocrop messes up'
  )
  args = parser.parse_args()

  # Setup device

  tmpout = tempfile.TemporaryFile(mode='r+b')
  sys.stdout = open(sys.stdout.fileno(), 'wb')
  dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)
  atexit.register(lambda: usb.util.dispose_resources(dev))

  if dev is None:
    print('DS-40 is not available', file=sys.stderr)
    exit(1)

  dev.set_configuration()

  def read():
    d = dev.read(EP_IN, IN_BUF_SIZE)
    return bytes(d)

  def write(d):
    dev.write(EP_OUT, d)

  write(b'FIN x0000000') # finish off anything currently going on
  read() # throw away the response, don't need it
  write(b'\x1c\x58') # put scanner in control mode
  if read() != b'\x06':
    print('scanner didn\'t ACK control mode', file=sys.stderr)
    exit(1)

  # Setup parameters:
  # COL sets image type as defined by CLRS{}
  # GMM sets gamma: (UG10 -> 1.0, UG18 -> 1.8)
  # CMX sets color correction: (UNIT -> disable, UM08 -> for C024)
  # RSM, RSS sets resolution

  width, height = int(args.res * MAX_W), int(args.res * MAX_H)

  params = deque()
  params.append(b'#ADF#COL')
  params.append(CLRS[args.color])
  params.append(b'#FMTJPG #JPGd%03d#GMMUG18#CMXUNIT' % args.quality)
  params.append(
    b'#RSMi%07d#RSSi%07d' % (args.res, args.res))
  params.append(b'#ACQi%07di%07di%07di%07d' % (0, 0, width, height))
  params.append(b'#PAGd000#BSZi%07d' % IN_BUF_SIZE)
  for gmt in (b'RED', b'GRN', b'BLU'):
    params.append(b'#GMT' + gmt + b' h100')
    params.append(bytes(range(256)))
  params = b''.join(params)

  write(b'PARAx%07X' % len(params))
  write(params)
  if b'#parOK' not in read():
    print('scanner didn\'t accept params', file=sys.stderr)
    exit(1)

  # Start scanning

  write(b'TRDTx0000000')
  ret = read()
  if b'#errADF PE' in ret:
    print('no paper to scan', file=sys.stderr)
    exit(1)

  final_height = None
  while True:
    write(b'IMG x0000000')
    ret = read()
    if not ret.startswith(b'IMG x'):
      print('bad image data ack', file=sys.stderr)
      exit(1)
    if b'#errADF PE' in ret:
      break
    pen_idx = ret.find(b'#peni')
    if pen_idx >= 0:
      final_height = int(ret[pen_idx + 13:pen_idx + 20])
    dl = int(ret[5:12], 16)
    while dl > 0:
      d = read()
      dl -= len(d)
      tmpout.write(d)

  write(b'FIN x0000000')
  read()
  tmpout.flush()
  tmpout.seek(0)

  if final_height is None:
    print('no final height reported', file=sys.stderr)
    exit(1)

  # Analyse the output for better cropping if PIL is available

  left, right = 0, width
  try:
    from PIL import Image
  except ImportError:
    if not args.no_crop:
      print('PIL not installed - disabled autocrop', file=sys.stderr)
      args.no_crop = True

  if not args.no_crop:
    vnorm = (lambda x: (x, x, x)) if args.color == 'g' else lambda x: x
    line = [vnorm(p)
      for p in Image.open(tmpout).crop((0, 0, width, final_height))
        .resize((width, 1), 1).getdata()]
    streak_th = int((MIN_HFEATURE_LEN / MAX_H) * len(line))
    blank = vnorm(BLANKS[args.color])
    left = find_edge(line, blank, BLANK_VARI, streak_th)
    right = find_edge(reversed(line), blank, BLANK_VARI, streak_th)
    right = width - right
    if left >= right:
      left, right = 0, width
      print('couldn\'t find edges', file=sys.stderr)
    tmpout.seek(0)

  # Crop

  jpegtran = Popen(
    ['jpegtran', '-crop', '%dx%d+%d+0' % (
      right - left, final_height, left
    )], stdin=tmpout, stderr=open(os.devnull, 'wb')
  )
  jpegtran.wait()
  exit(0)

if __name__ == '__main__':
  main()
