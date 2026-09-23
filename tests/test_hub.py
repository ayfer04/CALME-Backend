import pytest

from app.ws.hub import Hub


class FauxSocket:
    def __init__(self):
        self.recus = []

    async def send_json(self, donnees):
        self.recus.append(donnees)


@pytest.mark.asyncio
async def test_diffuse_aux_abonnes_de_la_session():
    hub = Hub()
    a, b, autre = FauxSocket(), FauxSocket(), FauxSocket()
    hub.rejoindre(1, a)
    hub.rejoindre(1, b)
    hub.rejoindre(2, autre)

    await hub.diffuser(1, {"type": "notice", "payload": {"level": "info", "message": "ok"}})

    assert len(a.recus) == 1
    assert len(b.recus) == 1
    assert autre.recus == []


@pytest.mark.asyncio
async def test_un_socket_mort_ne_bloque_pas_les_autres():
    class SocketMort(FauxSocket):
        async def send_json(self, donnees):
            raise RuntimeError("ferme")

    hub = Hub()
    mort, vivant = SocketMort(), FauxSocket()
    hub.rejoindre(1, mort)
    hub.rejoindre(1, vivant)

    await hub.diffuser(1, {"type": "notice", "payload": {}})

    assert len(vivant.recus) == 1
    assert mort not in hub._salles[1]


@pytest.mark.asyncio
async def test_la_salle_se_vide_quand_tout_le_monde_quitte():
    hub = Hub()
    socket = FauxSocket()
    hub.rejoindre(1, socket)
    assert 1 in hub._salles

    hub.quitter(1, socket)
    assert 1 not in hub._salles


@pytest.mark.asyncio
async def test_la_salle_se_vide_quand_tous_les_sockets_morts_sont_retires():
    class SocketMort(FauxSocket):
        async def send_json(self, donnees):
            raise RuntimeError("ferme")

    hub = Hub()
    mort = SocketMort()
    hub.rejoindre(1, mort)
    assert 1 in hub._salles

    await hub.diffuser(1, {"type": "notice", "payload": {}})
    assert 1 not in hub._salles
