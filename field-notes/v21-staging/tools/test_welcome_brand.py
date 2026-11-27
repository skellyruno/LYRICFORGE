import pytest
from apply_welcome_brand import transform, ART, DECOR, LINK

@pytest.mark.parametrize('art', [ART, DECOR])
def test_welcome_identity(art):
    old = '<head></head><div id="welcome"><em>YOUR WORDS.</em>' + art + '</div><button id="openCreatorWelcome">Create</button>'
    out = transform(old)
    assert out.count(ART) == 1 and out.count(LINK) == 1
    assert '<button id="openCreatorWelcome">Create</button>' in out
    assert transform(out) == out

def test_unexpected_anchor_rejected():
    with pytest.raises(ValueError):
        transform('<head></head><div id="welcome"><em>YOUR WORDS.</em></div>')
