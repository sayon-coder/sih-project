"""
Tests for product endpoints.
"""
import pytest
from fastapi.testclient import TestClient


class TestProductCreation:
    """Tests for product creation endpoint."""

    def test_create_product_success(self, client, auth_headers):
        """Test successful product creation."""
        response = client.post(
            "/api/products",
            json={
                "name": "Test Ashwagandha Product",
                "description": "A test product for Ashwagandha extract"
            },
            headers=auth_headers
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["name"] == "Test Ashwagandha Product"
        assert "id" in data["data"]
        assert "current_version_id" in data["data"]

    def test_create_product_without_auth(self, client):
        """Test product creation without authentication."""
        response = client.post(
            "/api/products",
            json={
                "name": "Test Product",
                "description": "Test description"
            }
        )

        assert response.status_code == 401

    def test_create_product_minimal(self, client, auth_headers):
        """Test creating product with minimal data."""
        response = client.post(
            "/api/products",
            json={"name": "Minimal Product"},
            headers=auth_headers
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["name"] == "Minimal Product"


class TestProductListing:
    """Tests for product listing endpoint."""

    def test_list_products_empty(self, client, auth_headers):
        """Test listing products when user has none."""
        response = client.get("/api/products", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"] == []

    def test_list_products_with_data(self, client, auth_headers):
        """Test listing products after creating some."""
        # Create a product first
        client.post(
            "/api/products",
            json={"name": "Product 1"},
            headers=auth_headers
        )

        response = client.get("/api/products", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["data"][0]["name"] == "Product 1"


class TestProductRetrieval:
    """Tests for getting a single product."""

    def test_get_product_success(self, client, auth_headers):
        """Test getting a product by ID."""
        # Create product
        create_response = client.post(
            "/api/products",
            json={"name": "Test Product"},
            headers=auth_headers
        )
        product_id = create_response.json()["data"]["id"]

        # Get product
        response = client.get(f"/api/products/{product_id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["id"] == product_id
        assert data["data"]["name"] == "Test Product"

    def test_get_product_not_found(self, client, auth_headers):
        """Test getting a non-existent product."""
        response = client.get("/api/products/99999", headers=auth_headers)

        assert response.status_code == 404


class TestProductUpdate:
    """Tests for updating products."""

    def test_update_product_success(self, client, auth_headers):
        """Test updating a product."""
        # Create product
        create_response = client.post(
            "/api/products",
            json={"name": "Original Name"},
            headers=auth_headers
        )
        product_id = create_response.json()["data"]["id"]

        # Update product
        response = client.put(
            f"/api/products/{product_id}",
            json={"name": "Updated Name", "description": "New description"},
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["name"] == "Updated Name"
        assert data["data"]["description"] == "New description"


class TestProductDeletion:
    """Tests for deleting products."""

    def test_delete_product_success(self, client, auth_headers):
        """Test deleting a product."""
        # Create product
        create_response = client.post(
            "/api/products",
            json={"name": "To Be Deleted"},
            headers=auth_headers
        )
        product_id = create_response.json()["data"]["id"]

        # Delete product
        response = client.delete(f"/api/products/{product_id}", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify it's deleted (should return 404)
        get_response = client.get(f"/api/products/{product_id}", headers=auth_headers)
        assert get_response.status_code == 404


class TestProductVersions:
    """Tests for product versioning."""

    def test_initial_version_created(self, client, auth_headers):
        """Test that initial version is created with product."""
        # Create product
        create_response = client.post(
            "/api/products",
            json={"name": "Versioned Product"},
            headers=auth_headers
        )
        product_id = create_response.json()["data"]["id"]

        # List versions
        response = client.get(f"/api/products/{product_id}/versions", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["version_number"] == 1

    def test_create_new_version(self, client, auth_headers):
        """Test creating a new version."""
        # Create product
        create_response = client.post(
            "/api/products",
            json={"name": "Multi Version Product"},
            headers=auth_headers
        )
        product_id = create_response.json()["data"]["id"]

        # Create new version
        response = client.post(
            f"/api/products/{product_id}/versions",
            json={"change_reason": "Updated formulation"},
            headers=auth_headers
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["version_number"] == 2
        assert data["data"]["change_reason"] == "Updated formulation"

    def test_get_specific_version(self, client, auth_headers):
        """Test getting a specific version."""
        # Create product
        create_response = client.post(
            "/api/products",
            json={"name": "Specific Version Product"},
            headers=auth_headers
        )
        product_id = create_response.json()["data"]["id"]

        # Get version 1
        version_id = create_response.json()["data"]["current_version_id"]
        response = client.get(
            f"/api/products/{product_id}/versions/{version_id}",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["version_number"] == 1


class TestProductPassport:
    """Tests for product passport endpoint."""

    def test_get_product_passport(self, client, auth_headers):
        """Test getting complete product passport."""
        # Create product
        create_response = client.post(
            "/api/products",
            json={
                "name": "Passport Product",
                "description": "Full passport test"
            },
            headers=auth_headers
        )

        assert create_response.status_code == 201, f"Failed to create product: {create_response.json()}"
        product_id = create_response.json()["data"]["id"]

        # Get passport
        response = client.get(f"/api/products/{product_id}/passport", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        passport = data["data"]
        assert "product" in passport
        assert "current_version" in passport
        assert "version_count" in passport
        assert passport["product"]["name"] == "Passport Product"
        assert passport["version_count"] == 1
