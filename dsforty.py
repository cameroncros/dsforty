#!/usr/bin/env python
# dsforty.py - Scan a page on Epson DS-40
# Copyright 2015 (C) Mansour Behabadi <mansour@oxplot.com>
import argparse
import io
import sys
import threading
import time
from collections import deque

import usb.core
import usb.util
from PIL import Image

IN_BUF_SIZE = 1024 ** 2
VENDOR = 0x04b8
PRODUCT = 0x0152
EP_OUT = 0x02
EP_IN = 0x81
MAX_W = 8.5  # in inches
MAX_H = 14  # in inches

CLRS = {'g': b'M008', 'c': b'C024'}


class DSForty:

    def __init__(self, args):
        self.args = args
        self.dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)

        if self.dev is None:
            print('DS-40 is not available', file=sys.stderr)
            return

        self.dev.set_configuration()

        self.width, self.height = int(self.args.res * MAX_W), int(self.args.res * MAX_H)

        if not self.args.filename:
            self.args.filename = "scanimage_%04d.jpg"

        if not self.args.continuous:
            self.run_scan(self.args.filename % 1)
            return

        i = 46
        while self.args.continuous:
            i += 1
            current_file = self.args.filename % i
            self.run_scan(current_file)

    def read(self):
        d = self.dev.read(EP_IN, IN_BUF_SIZE)
        return bytes(d)

    def write(self, d):
        self.dev.write(EP_OUT, d)

    def setup_scanner(self):
        # Setup parameters:
        # COL sets image type as defined by CLRS{}
        # GMM sets gamma: (UG10 -> 1.0, UG18 -> 1.8)
        # CMX sets color correction: (UNIT -> disable, UM08 -> for C024)
        # RSM, RSS sets resolution
        self.dev.reset()

        while True:
            try:
                time.sleep(0.001)
                self.write(b'\x1c\x58')  # put scanner in control mode
                if self.read() != b'\x06':
                    print('scanner didn\'t ACK control mode', file=sys.stderr)
                    exit(1)
                break
            except usb.USBError as e:
                pass

        params = deque()
        params.append(b'#ADF#COL')
        params.append(CLRS[self.args.color])
        params.append(b'#FMTJPG #JPGd%03d#GMMUG18#CMXUNIT' % self.args.quality)
        params.append(
            b'#RSMi%07d#RSSi%07d' % (self.args.res, self.args.res))
        params.append(b'#ACQi%07di%07di%07di%07d' % (0, 0, self.width, self.height))
        params.append(b'#PAGd000#BSZi%07d' % IN_BUF_SIZE)
        for gmt in (b'RED', b'GRN', b'BLU'):
            params.append(b'#GMT' + gmt + b' h100')
            params.append(bytes(range(256)))
        params = b''.join(params)
        self.write(b'PARAx%07X' % len(params))
        self.write(params)
        if b'#parOK' not in self.read():
            print('scanner didn\'t accept params', file=sys.stderr)
            exit(-1)

    def run_scan(self, filename):
        self.setup_scanner()

        # Start scanning
        tmpout = io.BytesIO()
        print('waiting for paper', file=sys.stderr)
        while True:
            self.write(b'TRDTx0000000')
            ret = self.read()
            if b'#errADF PE' in ret:
                time.sleep(0.001)
                continue
            # We have paper, break and continue
            break
        print('paper in scanner, scan starting', file=sys.stderr)

        final_height = None
        while True:
            self.write(b'IMG x0000000')
            ret = self.read()
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
                d = self.read()
                dl -= len(d)
                tmpout.write(d)

        threading.Thread(target=self.dev.reset, daemon=True).start()
        tmpout.flush()
        tmpout.seek(0)

        if final_height is None:
            print('no final height reported', file=sys.stderr)
            exit(1)

        # Crop
        img = Image.open(tmpout)
        img = img.crop((0, 0, self.width, final_height))
        img.save(filename)

        print('Scanned to: %s' % filename, file=sys.stderr)


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
        default=600,
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
        type=int,
        default=100,
        help='quality of output JPEG, between 1..100 - defaults to 100'
    )
    parser.add_argument(
        '-n', '--no-crop',
        action='store_true',
        help='do not crop vertical borders - use when autocrop messes up'
    )
    parser.add_argument(
        '-f', '--file-name',
        dest='filename',
        help='the filename to save to. If in continuous mode, print formaters can be used'
    )
    parser.add_argument(
        '-C', '--continuous',
        action='store_true',
        help='Continuously scan documents as they are inserted. Use a filename such as \
          "Photo-%.4d.jpg" to automatically increment the photo version'
    )
    args = parser.parse_args()
    DSForty(args)


if __name__ == '__main__':
    main()
