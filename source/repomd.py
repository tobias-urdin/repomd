import datetime
import gzip
import io
import pathlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET


_ns = {
    'common': 'http://linux.duke.edu/metadata/common',
    'repo':   'http://linux.duke.edu/metadata/repo',
    'rpm':    'http://linux.duke.edu/metadata/rpm'
}


class NotRepoException(Exception):
    pass


def _load_mirrorlist(url):
    mirrors = []

    try:
        with urllib.request.urlopen(url) as response:
            result = response.read().decode('utf-8')
            result = result.splitlines()

            for r in result:
                u = urllib.parse.urlparse(r)

                if u.scheme in ['http', 'https'] and u.netloc:
                    mirrors.append(u.geturl())
    except Exception:
        pass

    return mirrors


def _load_repomd(base, path):
    # first we must get the repomd.xml file
    repomd_path = path / 'repodata' / 'repomd.xml'
    repomd_url = base._replace(path=str(repomd_path)).geturl()

    # download and parse repomd.xml
    try:
        with urllib.request.urlopen(repomd_url) as response:
            repomd_xml = ET.fromstring(response.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotRepoException(f'{repomd_url} does not exist') from None
        else:
            raise e

    return repomd_xml


def _parse_baseurl(baseurl):
    base = urllib.parse.urlparse(baseurl)
    path = pathlib.PurePosixPath(base.path)

    return base, path


def load(baseurl):
    base, path = _parse_baseurl(baseurl)
    repomd_xml = None

    try:
        repomd_xml = _load_repomd(base, path)
    except NotRepoException:
        mirrors = _load_mirrorlist(baseurl)

        for mirror in mirrors:
            try:
                base, path = _parse_baseurl(mirror)
                repomd_xml = _load_repomd(base, path)
            except Exception:
                continue
            else:
                break

        if repomd_xml is None:
            raise

    # determine the location of *primary.xml.gz
    primary_element = repomd_xml.find('repo:data[@type="primary"]/repo:location', namespaces=_ns)
    primary_path = path / primary_element.get('href')
    primary_url = base._replace(path=str(primary_path)).geturl()

    # download and parse *-primary.xml
    with urllib.request.urlopen(primary_url) as response:
        with io.BytesIO(response.read()) as compressed:
            with gzip.GzipFile(fileobj=compressed) as uncompressed:
                metadata = ET.fromstring(uncompressed.read())

    return Repo(baseurl, metadata)


class Repo:
    """A dnf/yum repository."""

    __slots__ = ['baseurl', '_metadata']

    def __init__(self, baseurl, metadata):
        self.baseurl = baseurl
        self._metadata = metadata

    def __repr__(self):
        return f'<{self.__class__.__name__}: "{self.baseurl}">'

    def __str__(self):
        return self.baseurl

    def __len__(self):
        return int(self._metadata.get('packages'))

    def __iter__(self):
        for element in self._metadata:
            yield Package(element)

    def find(self, name):
        results = self._metadata.findall(f'common:package[common:name="{name}"]', namespaces=_ns)
        if results:
            return Package(results[-1])
        else:
            return None

    def findall(self, name):
        return [
            Package(element)
            for element in self._metadata.findall(f'common:package[common:name="{name}"]', namespaces=_ns)
        ]


class Package:
    """An RPM package from a repository."""

    __slots__ = ['_element']

    def __init__(self, element):
        self._element = element

    @property
    def name(self):
        return self._element.findtext('common:name', namespaces=_ns)

    @property
    def arch(self):
        return self._element.findtext('common:arch', namespaces=_ns)

    @property
    def summary(self):
        return self._element.findtext('common:summary', namespaces=_ns)

    @property
    def description(self):
        return self._element.findtext('common:description', namespaces=_ns)

    @property
    def packager(self):
        return self._element.findtext('common:packager', namespaces=_ns)

    @property
    def url(self):
        return self._element.findtext('common:url', namespaces=_ns)

    @property
    def license(self):
        return self._element.findtext('common:format/rpm:license', namespaces=_ns)

    @property
    def vendor(self):
        return self._element.findtext('common:format/rpm:vendor', namespaces=_ns)

    @property
    def sourcerpm(self):
        return self._element.findtext('common:format/rpm:sourcerpm', namespaces=_ns)

    @property
    def build_time(self):
        build_time = self._element.find('common:time', namespaces=_ns).get('build')
        return datetime.datetime.fromtimestamp(int(build_time))

    @property
    def location(self):
        return self._element.find('common:location', namespaces=_ns).get('href')

    @property
    def _version_info(self):
        return self._element.find('common:version', namespaces=_ns)

    @property
    def epoch(self):
        return self._version_info.get('epoch')

    @property
    def version(self):
        return self._version_info.get('ver')

    @property
    def release(self):
        return self._version_info.get('rel')

    @property
    def vr(self):
        version_info = self._version_info
        v = version_info.get('ver')
        r = version_info.get('rel')
        return f'{v}-{r}'

    @property
    def nvr(self):
        return f'{self.name}-{self.vr}'

    @property
    def evr(self):
        version_info = self._version_info
        e = version_info.get('epoch')
        v = version_info.get('ver')
        r = version_info.get('rel')
        if int(e):
            return f'{e}:{v}-{r}'
        else:
            return f'{v}-{r}'

    @property
    def nevr(self):
        return f'{self.name}-{self.evr}'

    @property
    def nevra(self):
        return f'{self.nevr}.{self.arch}'

    @property
    def _nevra_tuple(self):
        return self.name, self.epoch, self.version, self.release, self.arch

    def __eq__(self, other):
        return self._nevra_tuple == other._nevra_tuple

    def __hash__(self):
        return hash(self._nevra_tuple)

    def __repr__(self):
        return f'<{self.__class__.__name__}: "{self.nevra}">'
