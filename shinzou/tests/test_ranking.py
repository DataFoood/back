from shinzou.ranking import Candidate, _zscores, rank


def test_zscores_mean_zero_std_one():
    z = _zscores([1.0, 2.0, 3.0, 4.0, 5.0])
    assert abs(sum(z)) < 1e-9, "soma dos z-scores ~ 0 (média 0)"
    # desvio padrão populacional dos z-scores = 1
    from statistics import pstdev
    assert abs(pstdev(z) - 1.0) < 1e-9


def test_zscores_constant_returns_zeros():
    assert _zscores([7.0, 7.0, 7.0]) == [0.0, 0.0, 0.0]


def test_semantic_dominates_preference():
    # A: melhor semântica, preferência zero. B: pior semântica, preferência alta.
    # peso semântico (1.0) > preferência (0.5) -> A ganha. Preferência NÃO sobrepõe.
    candidates = [
        Candidate(restaurant_id=1, semantic=0.95, preference=0.0, review=3.0),
        Candidate(restaurant_id=2, semantic=0.50, preference=10.0, review=3.0),
    ]
    ranked = rank(candidates, w_semantic=1.0, w_preference=0.5, w_review=0.3, limit=15)
    assert ranked[0][0] == 1, "semântica manda mais que preferência"


def test_preference_breaks_tie():
    # mesma semântica/review -> preferência desempata
    candidates = [
        Candidate(restaurant_id=1, semantic=0.8, preference=0.0, review=4.0),
        Candidate(restaurant_id=2, semantic=0.8, preference=5.0, review=4.0),
    ]
    ranked = rank(candidates, w_semantic=1.0, w_preference=0.5, w_review=0.3, limit=15)
    assert ranked[0][0] == 2


def test_limit_truncates():
    candidates = [
        Candidate(restaurant_id=i, semantic=i / 10, preference=0.0, review=0.0)
        for i in range(20)
    ]
    ranked = rank(candidates, 1.0, 0.5, 0.3, limit=15)
    assert len(ranked) == 15


def test_empty():
    assert rank([], 1.0, 0.5, 0.3, 15) == []
