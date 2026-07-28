"""
Internal reference-data endpoints. Nothing outside this domain should call
adapters/treasury_adapter.py directly — going through service.py here is
what gives every external call the audit trail and 6-hour cache the
reference-data doctrine requires.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.reference_data.adapters.treasury_adapter import TreasuryAPIError
from app.domains.reference_data.adapters.payroll_tax_adapter import (
    PayrollTaxAPIError,
    PayrollTaxAuthError,
    PayrollTaxRateLimitError,
)
from app.domains.reference_data.adapters.census_adapter import CensusAPIError
from app.domains.reference_data.adapters.bls_adapter import BLSAPIError
from app.domains.reference_data.adapters.bea_adapter import BEAAPIError
from app.domains.reference_data.adapters.fred_adapter import FREDAPIError
from app.domains.reference_data.adapters.govinfo_adapter import GovInfoAPIError
from app.domains.reference_data.adapters.federal_register_adapter import FederalRegisterAPIError
from app.domains.reference_data.adapters.ecfr_adapter import ECFRAPIError
from app.domains.reference_data.adapters.congress_adapter import CongressAPIError
from app.domains.reference_data.models import ReferenceSourceBundle
from app.domains.reference_data.service import (
    get_exchange_rate_bundle,
    get_payroll_tax_bundle,
    get_census_income_poverty_bundle,
    get_cpi_bundle,
    get_gdp_bundle,
    get_interest_rates_bundle,
    get_cfr_section_bundle,
    get_federal_register_document_bundle,
    get_ecfr_section_bundle,
    get_congress_bill_bundle,
)

router = APIRouter(prefix="/internal/reference", tags=["reference_data"])


@router.get("/exchange-rates", response_model=ReferenceSourceBundle)
async def get_exchange_rates_endpoint(
    currency: str | None = None,
    since: str = "2020-01-01",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_exchange_rate_bundle(
            db,
            currency=currency,
            since=since,
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
        )
    except TreasuryAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/payroll-tax-rates", response_model=ReferenceSourceBundle)
async def get_payroll_tax_rates_endpoint(
    work_state: str,
    pay_date: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_payroll_tax_bundle(
            db,
            work_state=work_state,
            pay_date=pay_date,
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
        )
    except PayrollTaxAuthError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except PayrollTaxRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except PayrollTaxAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/census-income-poverty", response_model=ReferenceSourceBundle)
async def get_census_income_poverty_endpoint(
    state_fips: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_census_income_poverty_bundle(
            db,
            state_fips=state_fips,
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
        )
    except CensusAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/cpi-inflation", response_model=ReferenceSourceBundle)
async def get_cpi_inflation_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_cpi_bundle(db, tenant_id=current_user.tenant_id, actor_id=current_user.id)
    except BLSAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/gdp", response_model=ReferenceSourceBundle)
async def get_gdp_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_gdp_bundle(db, tenant_id=current_user.tenant_id, actor_id=current_user.id)
    except BEAAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/interest-rates", response_model=ReferenceSourceBundle)
async def get_interest_rates_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_interest_rates_bundle(db, tenant_id=current_user.tenant_id, actor_id=current_user.id)
    except FREDAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/cfr-section", response_model=ReferenceSourceBundle)
async def get_cfr_section_endpoint(
    section_number: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_cfr_section_bundle(
            db, section_number=section_number, tenant_id=current_user.tenant_id, actor_id=current_user.id,
        )
    except GovInfoAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/federal-register-document", response_model=ReferenceSourceBundle)
async def get_federal_register_document_endpoint(
    document_number: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_federal_register_document_bundle(
            db, document_number=document_number, tenant_id=current_user.tenant_id, actor_id=current_user.id,
        )
    except FederalRegisterAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/ecfr-section", response_model=ReferenceSourceBundle)
async def get_ecfr_section_endpoint(
    section_number: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_ecfr_section_bundle(
            db, section_number=section_number, tenant_id=current_user.tenant_id, actor_id=current_user.id,
        )
    except ECFRAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/congress-bill", response_model=ReferenceSourceBundle)
async def get_congress_bill_endpoint(
    congress: int,
    bill_type: str,
    bill_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReferenceSourceBundle:
    try:
        return await get_congress_bill_bundle(
            db, congress=congress, bill_type=bill_type, bill_number=bill_number,
            tenant_id=current_user.tenant_id, actor_id=current_user.id,
        )
    except CongressAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

