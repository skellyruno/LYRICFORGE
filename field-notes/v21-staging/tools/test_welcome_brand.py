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

from apply_welcome_brand import add_preferences, PREF, SCRIPT

def test_preferences_preserve_welcome_actions_and_are_idempotent():
    html = '<body><div id="welcome"><div class="welcome-content"><div class="welcome-secondary-actions"><button id="openCreatorWelcome">Create</button></div></div>' + ART + '</div></body>'
    out = add_preferences(html)
    assert out.count(PREF) == out.count(SCRIPT) == 1
    assert out.count('id="openCreatorWelcome"') == 1
    assert add_preferences(out) == out

def test_preferences_reject_unexpected_footer():
    with pytest.raises(ValueError, match='footer'):
        add_preferences('<body></body>')
