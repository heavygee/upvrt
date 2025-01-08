import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['LOGIN_DISABLED'] = True  # Disable login requirement for testing
    with app.test_client() as client:
        yield client

def test_index_route(client):
    """Test the index route returns 200"""
    rv = client.get('/upvrt/')  # Updated to use correct route
    assert rv.status_code == 200

def test_health_check(client):
    """Test the health check endpoint"""
    rv = client.get('/upvrt/health')
    assert rv.status_code == 200
    assert b'ok' in rv.data.lower()

def test_privacy_route(client):
    """Test privacy policy route returns 200"""
    rv = client.get('/upvrt/privacy')
    assert rv.status_code == 200

def test_tos_route(client):
    """Test terms of service route returns 200"""
    rv = client.get('/upvrt/tos')
    assert rv.status_code == 200 