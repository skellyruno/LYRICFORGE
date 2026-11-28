import pytest
from studio_expression_worker import validate,DIRECTIONS

def test_expression_worker_input_bounds_and_controls():
    assert validate({'phrases':['Shape the sound.'],'directions':['reveal']})==[('Shape the sound.','reveal')]
    assert DIRECTIONS['reveal'][0]>DIRECTIONS['detail'][0]
    for body in ({'phrases':['x'],'directions':['unknown']},{'phrases':['x'],'directions':[]},{'phrases':['x'*241],'directions':['steady']},{'phrases':['x'],'directions':['steady'],'voice_file':'private.wav'}):
        with pytest.raises(ValueError):validate(body)
