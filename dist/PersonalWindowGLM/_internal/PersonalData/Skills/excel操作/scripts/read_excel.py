import sys

import pandas as pd

def read_excel(path: str, sheet_name: str = '最小配置'):
    df = pd.read_excel(path, sheet_name=sheet_name)
    return df


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    df = read_excel(path)
    print(df)
