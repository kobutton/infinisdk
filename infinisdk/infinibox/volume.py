from capacity import GB
from storage_interfaces.scsi.abstracts import ScsiVolume
from ..core.type_binder import TypeBinder
from ..core import Field, CapacityType, MillisecondsDatetimeType
from ..core.exceptions import InfiniSDKException, ObjectNotFound, TooManyObjectsFound
from ..core.api.special_values import Autogenerate
from ..core.bindings import RelatedObjectBinding
from ..core.utils import deprecated, DONT_CARE
from .base_data_entity import BaseDataEntity
from .lun import LogicalUnit, LogicalUnitContainer
from .scsi_serial import SCSISerial


class VolumesBinder(TypeBinder):

    def create_many(self, *args, **kwargs):
        """
        Creates multiple volumes with a single call. Parameters are just like ``volumes.create``, only with the
        addition of the ``count`` parameter

        :param count: number of volumes to create. Defaults to 1.
        :rtype: list of volumes
        """
        name = kwargs.pop('name', None)
        if name is None:
            name = Autogenerate('vol_{uuid}').generate()
        count = kwargs.pop('count', 1)
        return [self.create(*args, name='{0}_{1}'.format(name, i), **kwargs)
                for i in range(1, count + 1)]


class Volume(BaseDataEntity):

    BINDER_CLASS = VolumesBinder

    FIELDS = [
        Field("id", type=int, is_identity=True,
              is_filterable=True, is_sortable=True),
        Field("name", creation_parameter=True, mutable=True, is_filterable=True,
            is_sortable=True, default=Autogenerate("vol_{uuid}")),
        Field("size", creation_parameter=True, mutable=True,
              is_filterable=True, is_sortable=True, default=GB, type=CapacityType),
        Field("used_size", api_name="used", type=CapacityType),
        Field("allocated", type=CapacityType, is_sortable=True, is_filterable=True),
        Field("tree_allocated", type=CapacityType),
        Field("pool", type='infinisdk.infinibox.pool:Pool', api_name="pool_id", creation_parameter=True, is_filterable=True, is_sortable=True,
              binding=RelatedObjectBinding()),

        Field("type", cached=True, is_filterable=True, is_sortable=True),
        Field("parent", type='infinisdk.infinibox.volume:Volume', cached=True, api_name="parent_id",
                binding=RelatedObjectBinding('volumes'), is_filterable=True),
        Field("provisioning", api_name="provtype", mutable=True, creation_parameter=True,
                is_filterable=True, is_sortable=True, default="THICK"),
        Field("created_at", cached=True, type=MillisecondsDatetimeType, is_sortable=True, is_filterable=True),
        Field("updated_at", type=MillisecondsDatetimeType, is_sortable=True, is_filterable=True),
        Field("serial", type=SCSISerial, is_filterable=True, is_sortable=True),
        Field("ssd_enabled", type=bool, mutable=True, creation_parameter=True, is_filterable=True, is_sortable=True, optional=True),
        Field("write_protected", type=bool, mutable=True, creation_parameter=True, optional=True
              , is_filterable=True, is_sortable=True),
        Field("depth", cached=True, type=int, is_sortable=True, is_filterable=True),
        Field("mapped", type=bool, is_sortable=True, is_filterable=True),
        Field("has_children", type=bool),
        Field('rmr_source', type=bool),
        Field('rmr_target', type=bool),
    ]

    @deprecated(message="Use volume.is_master instead")
    def is_master_volume(self):
        return self.is_master()

    def own_replication_snapshot(self, name=None):
        if not name:
            name = Autogenerate('vol_{uuid}')
        data = {'name': name}
        child = self._create(self.system, self.get_this_url_path().add_path('own_snapshot'), data=data)
        return child

    def _get_luns_data_from_url(self):
        res = self.system.api.get(self.get_this_url_path().add_path('luns'))
        return res.get_result()

    def get_lun(self, mapping_object):
        """Given either a host or a host cluster object, returns the single LU object mapped to this volume.

        An exception is raised if multiple matching LUs are found

        :param mapping_object: Either a host cluster or a host object to be checked
        :returns: None if no lu is found for this entity
        """
        def is_mapping_object_lu(lu_data):
            lu_mapping_id = lu_data['host_id'] or lu_data['host_cluster_id']
            return lu_mapping_id == mapping_object.id
        lus = [LogicalUnit(system=self.system, **lu_data)
               for lu_data in self._get_luns_data_from_url() if is_mapping_object_lu(lu_data)]
        if len(lus) > 1:
            raise InfiniSDKException("There shouldn't be multiple luns for volume-mapping object pair")
        return lus[0] if lus else None

    def get_logical_units(self):
        return LogicalUnitContainer.from_dict_list(self.system, self._get_luns_data_from_url())

    def get_replicas(self):
        pairs = self.system.api.get(self.get_this_url_path().add_path('replication_pairs')).response.json()['result']
        return [self.system.replicas.get_by_id_lazy(pair['replica_id']) for pair in pairs]

    def get_replica(self):
        returned = self.get_replicas()
        if len(returned) > 1:
            raise TooManyObjectsFound()
        elif len(returned) == 0:
            raise ObjectNotFound()
        return returned[0]

    def is_replicated(self, from_cache=DONT_CARE):
        """Returns True if this volume is a part of a replica, whether as source or as target
        """
        return any(self.get_fields(['rmr_source', 'rmr_target'], from_cache=from_cache).values())

    def unmap(self):
        """Unmaps a volume from its hosts
        """
        for lun in self.get_logical_units():
            lun.unmap()
        self.refresh('mapped')

    def has_children(self):
        return self.get_field("has_children")

ScsiVolume.register(Volume)