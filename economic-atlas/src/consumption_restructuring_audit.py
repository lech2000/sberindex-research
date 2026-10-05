"""Independent scalar features, least-squares ridge and persisted key audit."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from consumption_restructuring import cube_from_panel, deviations, dump, MONTHS, MODELS
from r9_strong_baselines import predict_block


def audit(repo, run):
    f = pd.read_parquet(run/'pre-2024-features.parquet').set_index('territory_id')
    panel = pd.read_parquet(repo/'economic-atlas/data/panel_v1.parquet')
    values, cats = cube_from_panel(panel, f.index)
    matches = pd.read_csv(run/'peers.csv')
    ixmap = {int(t): i for i, t in enumerate(f.index)}
    peers = np.full((len(f), 10), -1, int)
    supported = np.zeros(len(f), bool)
    for t, group in matches.loc[matches.status == 'SUPPORTED'].groupby('territory_id'):
        i = ixmap[int(t)]; supported[i] = True
        for j, pt in enumerate(group.sort_values('rank').peer_tid):
            peers[i, j] = ixmap[int(pt)]
    d = deviations(values, cats, peers, supported)
    med = np.median(values, axis=0)
    ix = np.flatnonzero(supported)
    p = pd.read_parquet(run/'predictions.parquet')
    fits = json.loads((run/'fits.json').read_text())
    feature_checks, ridge_checks, prediction_checks = 0, 0, 0
    # Scalar own/peer/common feature assembly on real data, excluding self.
    for i in ix[::100]:
        pp = peers[i][peers[i] >= 0]
        assert i not in pp
        for mi in [0, 5, 10]:
            oi = mi+12
            own, peer = [], []
            for kind, cat in [('share', 'Маркетплейсы'), ('log', 'Маркетплейсы'),
                              ('log', 'Все категории'), ('share', 'Продовольствие'),
                              ('log', 'Продовольствие')]:
                c = cats.index(cat)
                if kind == 'share':
                    a = cats.index('Все категории')
                    x = 100*(values[:, oi, c]/values[:, oi, a]-values[:, oi-12, c]/values[:, oi-12, a])
                else:
                    x = np.log(values[:, oi, c]/values[:, oi-12, c])
                own.append(x[i]-np.median(np.delete(x, i)))
                peer.append(x[i]-np.median(x[pp]))
            np.testing.assert_allclose(own, d['own_x'][i, mi], rtol=1e-11, atol=1e-11)
            np.testing.assert_allclose(own+peer, d['peer_x'][i, mi], rtol=1e-11, atol=1e-11)
            feature_checks += 15
    for fit in fits:
        if fit['horizon'] != 1 or fit['origin'] not in ['2024-06', '2024-11'] or fit['model'] not in ['own_ridge', 'peer_ridge']:
            continue
        c, oi, ti = cats.index(fit['category']), MONTHS.index(fit['origin']), MONTHS.index(fit['target'])
        u = list(range(12, oi))
        assert fit['last_training_target'] <= fit['origin'] and fit['training_origins'] == [MONTHS[j] for j in u]
        y = np.concatenate([np.log(values[ix, j+1, c]/predict_block(values[:, :, c], med[:, c], j, j+1)['profile_ses'][ix]) for j in u])
        key = 'own_x' if fit['model'] == 'own_ridge' else 'peer_x'
        x = np.concatenate([d[key][ix, j-12] for j in u])
        mean, scale = x.mean(0), x.std(0); scale[scale == 0] = 1
        z = np.c_[np.ones(len(x)), (x-mean)/scale]
        penalty = np.zeros((x.shape[1], x.shape[1]+1))
        penalty[:, 1:] = np.sqrt(.1*len(x))*np.eye(x.shape[1])
        coef = np.linalg.lstsq(np.r_[z, penalty], np.r_[y, np.zeros(x.shape[1])], rcond=None)[0]
        np.testing.assert_allclose(coef, [fit['intercept']]+fit['beta'], rtol=1e-8, atol=1e-10)
        current = np.c_[np.ones(len(ix)), (d[key][ix, oi-12]-mean)/scale]
        expected = predict_block(values[:, :, c], med[:, c], oi, ti)['profile_ses'][ix]*np.exp(np.clip(current@coef, -.1, .1))
        subset = p.loc[(p.category == fit['category']) & (p.horizon == 1) & (p.origin == fit['origin']) & p.supported].set_index('territory_id').loc[f.index[ix]]
        np.testing.assert_allclose(expected, subset[fit['model']], rtol=1e-10, atol=1e-8)
        ridge_checks += 1; prediction_checks += len(ix)
    assert len(p) == 1896*6*6*3 and p.supported.sum() == len(ix)*6*6*3
    assert not p.duplicated(['territory_id', 'category', 'horizon', 'origin', 'target']).any()
    assert np.isfinite(p.loc[p.supported, MODELS]).all().all()
    unsupported = p.loc[~p.supported]
    assert unsupported[['calibration', 'own_ridge', 'peer_ridge']].isna().all().all()
    diagnostics = []
    for target, b in p.loc[p.supported & (p.horizon == 1) & (p.category == 'Все категории')].groupby('target'):
        fit = next(q for q in fits if q['category'] == 'Все категории' and q['model'] == 'calibration' and q['horizon'] == 1 and q['target'] == target)
        diagnostics.append({'target': target, 'past_mean_log_error': fit['intercept'],
                            'subsequent_mean_log_error': float(np.log(b.actual/b.profile_ses).mean())})
    result = {'status': 'PASS', 'independent_feature_values': feature_checks,
              'independent_augmented_lstsq_fits': ridge_checks,
              'real_predictions_checked': prediction_checks,
              'same_key_mask': True, 'unsupported_explicit': len(unsupported),
              'post_result_calibration_diagnostic': diagnostics,
              'scope': 'Numerical verification; no as-of or unseen-holdout verification'}
    dump(run/'independent-audit.json', result)
    return result


if __name__ == '__main__':
    a = argparse.ArgumentParser()
    a.add_argument('--repo', type=Path, required=True)
    a.add_argument('--run', type=Path, required=True)
    q = a.parse_args()
    print(json.dumps(audit(q.repo, q.run), ensure_ascii=False))
