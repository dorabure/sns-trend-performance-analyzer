from sqlalchemy import select

from app.db.models import ProviderConnection, ProviderSyncState


class ProviderRepository:
    @staticmethod
    def connections(session, project_id):
        return list(session.scalars(select(ProviderConnection).where(
            ProviderConnection.project_id == project_id).order_by(ProviderConnection.provider_type)))

    @staticmethod
    def connection(session, project_id, provider_type, *, lock=False):
        query = select(ProviderConnection).where(ProviderConnection.project_id == project_id,
                                                 ProviderConnection.provider_type == provider_type)
        return session.scalar(query.with_for_update() if lock else query)

    @staticmethod
    def states(session, connection_id):
        return list(session.scalars(select(ProviderSyncState).where(
            ProviderSyncState.provider_connection_id == connection_id).order_by(ProviderSyncState.sync_resource_type)))
