#!/usr/bin/env python
# dsforty.py - Scan a page on Epson DS-40
# Copyright 2015 (C) Mansour Behabadi <mansour@oxplot.com>

from subprocess import Popen, PIPE
from collections import deque
import argparse
import sys
import tempfile
import usb.core

IN_BUF_SIZE = 1024 ** 2
VENDOR = 0x04b8
PRODUCT = 0x0152
EP_OUT = 0x02
EP_IN = 0x81
MAX_W = 8.5 # in inches
MAX_H = 14 # in inches

CLRS = {'m': b'M001', 'g': b'M008', 'c': b'C024'}

def main():
  parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description='Scan a page on Epson DS-40'
  )
  parser.add_argument(
    '-r', '--resolution',
    choices=[300, 600],
    default=300,
    type=int,
    help='Scan resolution - defaults to 300 dpi'
  )
  parser.add_argument(
    '-c', '--color',
    choices=list(sorted(CLRS)),
    default='c',
    help='Scan color: `m` for mono, `g` for grayscale and `c` for color'
         ' - defaults to color'
  )
  args = parser.parse_args()

  # Setup device

  tmpout = tempfile.TemporaryFile(mode='r+b')
  sys.stdout = open(sys.stdout.fileno(), 'wb')
  dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)

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
    print('Scanner didn\'t ACK control mode', file=sys.stderr)
    exit(1)

  # Setup parameters:
  # COL sets image type as defined by CLRS{}
  # GMM sets gamma: (UG10 -> 1.0, UG18 -> 1.8)
  # CMX sets color correction: (UNIT -> disable, UM08 -> for C024)
  # RSM, RSS sets resolution

  width, height = args.resolution * MAX_W, args.resolution * MAX_H

  params = deque()
  params.append(b'#ADF#COL')
  params.append(CLRS[args.color])
  params.append(b'#FMTJPG #JPGd100#GMMUG18#CMXUNIT')
  params.append(
    b'#RSMi%07d#RSSi%07d' % (args.resolution, args.resolution))
  params.append(b'#ACQi0000000i0000000i%07di%07d' % (width, height))
  params.append(b'#PAGd000#BSZi1048576') # pages and buffer size
  for gmt in (b'RED', b'GRN', b'BLU'):
    params.append(b'#GMT' + gmt + b' h100')
    params.append(bytes(range(256)))
  params = b''.join(params)

  write(b'PARAx%07X' % len(params))
  write(params)
  if b'#parOK' not in read():
    print('Scanner didn\'t accept params', file=sys.stderr)
    exit(1)

  # Start scanning

  write(b'TRDTx0000000')
  ret = read()
  if b'#errADF PE' in ret:
    print('No paper to scan', file=sys.stderr)
    exit(1)

  final_height = None
  while True:
    write(b'IMG x0000000')
    ret = read()
    if not ret.startswith(b'IMG x'):
      print('Bad image data ack', file=sys.stderr)
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
  tmpout.flush()
  tmpout.seek(0)

  if final_height is None:
    print('No final height reported', file=sys.stderr)
    exit(1)

  # Crop the height

  jpegtran = Popen(
    ['jpegtran', '-crop', '%dx%d+0+0' % (width, final_height)],
    stdin=tmpout
  )
  jpegtran.wait()

if __name__ == '__main__':
  main()
