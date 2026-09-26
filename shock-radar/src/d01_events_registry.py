"""D01/R5: реестр синтетических сдвигов + правила matching/cooldown.

Лестница R5: до настройки детектора определить события, интервалы, источник
и confidence. Реальных размеченных шоков нет — честно строим СИНТЕТИКУ:
инжектируем сдвиги известного размера/начала в копии панели и фиксируем
реестр. Детектор (D01–D03, R7) оценивается на нём как технический тест.
Правила matching: окно ±1 мес вокруг начала, cooldown 3 мес между тревогами
одного ряда (повторные срабатывания не считаются новыми находками).
Ручная проверка: 10 случайных событий — сверка с реестром глазами.
"""
import json
import numpy as np
import pandas as pd

SEED = 20260923
N_EVENTS = 60
MATCH_WINDOW = 1
COOLDOWN = 3

def build(panel_path, out_path):
    rng = np.random.default_rng(SEED)
    df = pd.read_parquet(panel_path)
    df['date'] = pd.to_datetime(df['date'])
    months = sorted(df['date'].dt.to_period('M').unique().astype(str))
    # окно инжекта: 2024-03..2024-09 (есть история до и окно после для детекции)
    inject_months = [m for m in months if '2024-03' <= m <= '2024-09']
    tids = sorted(df['territory_id'].unique())
    cats = [c for c in sorted(df['category'].unique()) if c != 'Все категории']
    rows = []
    used = set()
    for i in range(N_EVENTS):
        for _ in range(100):
            tid = int(rng.choice(tids))
            cat = str(rng.choice(cats))
            onset = str(rng.choice(inject_months))
            key = (tid, cat)
            # cooldown: тот же ряд не трогаем чаще чем раз в 3 мес
            if any(abs(months.index(onset) - months.index(r['onset'])) < COOLDOWN
                   for r in rows if (r['tid'], r['cat']) == key):
                continue
            break
        size = float(rng.choice([0.15, 0.25, 0.40]))  # относительный сдвиг
        direction = str(rng.choice(['up', 'down']))
        length = int(rng.choice([2, 3, 4]))
        rows.append({'event_id': f'EV{i:03d}', 'tid': tid, 'cat': cat,
                     'onset': onset, 'length_m': length, 'rel_size': size,
                     'direction': direction, 'source': 'synthetic_assumption',
                     'confidence': 'exact (injected)'})
        used.add(key)
    reg = pd.DataFrame(rows)
    reg.to_parquet(out_path, index=False)
    with open(out_path.replace('.parquet', '_rules.json'), 'w') as f:
        json.dump({'matching_window_m': MATCH_WINDOW, 'cooldown_m': COOLDOWN,
                   'seed': SEED, 'n_events': len(reg),
                   'note': 'технический тест на синтетике, не заявление о реальных шоках'},
                  f, ensure_ascii=False, indent=1)
    # ручная проверка: 10 случайных
    sample = reg.sample(min(10, len(reg)), random_state=SEED)
    print(reg.groupby(['direction','length_m']).size().to_string())
    print('saved', len(reg), 'events; manual sample:')
    print(sample[['event_id','tid','cat','onset','rel_size','direction']].to_string(index=False))
    return reg

if __name__ == '__main__':
    import sys
    build(sys.argv[1], 'shock-radar/events/registry.parquet')
