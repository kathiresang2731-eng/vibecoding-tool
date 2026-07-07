from __future__ import annotations

import re

CONST_ARRAY_START_PATTERN = re.compile(r"const\s+(?P<name>\w+)\s*=\s*\[", re.MULTILINE)
SCOPED_COUNT_WORDS = {
  "one": 1,
  "two": 2,
  "three": 3,
  "four": 4,
  "five": 5,
  "six": 6,
  "seven": 7,
  "eight": 8,
  "nine": 9,
  "ten": 10,
}
TIGER_CONTENT_VARIANTS = [
  "Bengal Tiger",
  "Siberian Tiger",
  "Sumatran Tiger",
  "Indo-Chinese Tiger",
  "Malayan Tiger",
  "South China Tiger",
]
