#!/usr/bin/env python
# dsforty.py - Scan a page on Epson DS-40
# Copyright 2015 (C) Mansour Behabadi <mansour@oxplot.com>

from subprocess import Popen, PIPE
from collections import deque
import argparse
import itertools
import socket
import sys
import tempfile
import usb.core

MAX_W = 8.5 # in inches
MAX_H = 14 # in inches

CLRS = {'m': b'M001', 'g': b'M008', 'c': b'C024'}

class USBDev:

  DESC = 'usb'
  IN_BUF_SIZE = 1024 ** 2
  VENDOR = 0x04b8
  PRODUCT = 0x0152
  EP_OUT = 0x02
  EP_IN = 0x81
  NAME = 'Epson DS-40'

  @staticmethod
  def enum():
    return [USBDev(d) for d in usb.core.find(
      idVendor=USBDev.VENDOR, idProduct=USBDev.PRODUCT, find_all=True
    ) if d.product == USBDev.NAME]

  def __init__(self, usbdev):
    self.dev = usbdev

  def init(self):
    self.dev.set_configuration()

  def id(self):
    return self.dev.serial_number

  def read(self):
    d = self.dev.read(USBDev.EP_IN, USBDev.IN_BUF_SIZE)
    return bytes(d)

  def write(self, d):
    self.dev.write(USBDev.EP_OUT, d)

class NetDev:

  DESC = 'net'

  @staticmethod
  def enum():
    return [] # TODO

  def __init__(self, ip):
    self.ip = ip

  def init(self):
    pass # TODO

  def id(self):
    pass # TODO

  def read(self):
    pass # TODO

  def write(self, d):
    pass # TODO

DEV_TYPES = (USBDev, NetDev)

def all_devs():
  yield from itertools.chain(*(t.enum() for t in DEV_TYPES))

def do_list(parser, args):
  fmt = '{1}:{0}' if args.type else '{0}'
  for dev in all_devs():
    print(fmt.format(dev.id(), dev.DESC))

def do_scan(parser, args):

  fltr = lambda x: x.id() == args.id if args.id else lambda x: x
  devs = list(filter(fltr, all_devs()))
  if len(devs) == 0:
    print('no scanner found', file=sys.stderr)
    exit(1)
  if len(devs) > 1:
    print('more than one scanner found - use `-i` option to pick one',
      file=sys.stderr)
    exit(1)

  tmpout = tempfile.TemporaryFile(mode='r+b')
  sys.stdout = open(sys.stdout.fileno(), 'wb')

  # Setup device

  dev = devs[0]
  dev.init()

  dev.write(b'FIN x0000000') # finish off anything currently going on
  dev.read() # throw away the response, don't need it
  dev.write(b'\x1c\x58') # put scanner in control mode
  if dev.read() != b'\x06':
    print('scanner didn\'t ACK control mode', file=sys.stderr)
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

  dev.write(b'PARAx%07X' % len(params))
  dev.write(params)
  if b'#parOK' not in dev.read():
    print('scanner didn\'t accept params', file=sys.stderr)
    exit(1)

  # Start scanning

  dev.write(b'TRDTx0000000')
  ret = dev.read()
  if b'#errADF PE' in ret:
    print('no paper to scan', file=sys.stderr)
    exit(1)

  final_height = None
  while True:
    dev.write(b'IMG x0000000')
    ret = dev.read()
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
      d = dev.read()
      dl -= len(d)
      tmpout.write(d)

  dev.write(b'FIN x0000000')
  tmpout.flush()
  tmpout.seek(0)

  if final_height is None:
    print('no final height reported', file=sys.stderr)
    exit(1)

  # Crop the height

  jpegtran = Popen(
    ['jpegtran', '-crop', '%dx%d+0+0' % (width, final_height)],
    stdin=tmpout
  )
  jpegtran.wait()

def do_config(parser, args):
  pass # TODO

def main():
  parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description='Scan a page on Epson DS-40'
  )
  subparsers = parser.add_subparsers(
    title='main commands',
    dest='cmd'
  )
  subparsers.required = True

  parser_a = subparsers.add_parser(
    'scan',
    help='scan a page'
  )
  parser_a.add_argument(
    '-r', '--resolution',
    choices=[300, 600],
    default=300,
    type=int,
    help='scan resolution - defaults to 300 dpi'
  )
  parser_a.add_argument(
    '-c', '--color',
    choices=list(sorted(CLRS)),
    default='c',
    help='scan color: `m` for mono, `g` for grayscale and `c` for color'
         ' - defaults to color'
  )
  parser_a.add_argument(
    '-i', '--id',
    default=None,
    help='unique id of the scanner in case there are multiple available'
         ' - run `dsforty list` to get a list'
  )
  parser_a.set_defaults(fn=do_scan)

  parser_a = subparsers.add_parser(
    'list',
    help='list all available scanners'
  )
  parser_a.add_argument(
    '-t', '--type',
    action='store_true',
    help='display type of connection for each device'
  )
  parser_a.set_defaults(fn=do_list)

  parser_a = subparsers.add_parser(
    'config',
    help='configure scanner'
  )
  # TODO
  parser_a.set_defaults(fn=do_config)

  args = parser.parse_args()
  args.fn(parser, args)

if __name__ == '__main__':
  main()
