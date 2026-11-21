// Test de charge de POST /predict avec k6.
// Lancé DANS le cluster (load/k6/job.yaml) pour que le trafic passe par le Service et soit
// réparti entre tous les Pods : un port-forward depuis le PC ne viserait qu'un seul Pod.
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://ecg-api.ecg-dev.svc";
const payload = open("./beats.json"); // 8 vrais battements MIT-BIH (patients de test)

// MODE=steady : trafic constant et modéré (ex. pendant un déploiement canary, pour que
// l'analyse Prometheus dispose de mesures sur les Pods de la nouvelle version).
const STEADY = {
  trafic_constant: {
    executor: "constant-arrival-rate",
    rate: Number(__ENV.RATE || 5),
    timeUnit: "1s",
    duration: __ENV.DURATION || "15m",
    preAllocatedVUs: 10,
    maxVUs: 30,
  },
};

export const options = {
  scenarios: __ENV.MODE === "steady" ? STEADY : {
    montee_en_charge: {
      // Débit imposé (requêtes/s) plutôt qu'un nombre d'utilisateurs : la charge reste la même
      // même si l'API ralentit, ce qui révèle vraiment la saturation.
      executor: "ramping-arrival-rate",
      startRate: 2,
      timeUnit: "1s",
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { target: 10, duration: "1m" },  // échauffement
        { target: 40, duration: "2m" },  // montée : le HPA doit ajouter des Pods
        { target: 40, duration: "4m" },  // plateau : la latence doit se stabiliser
        { target: 0, duration: "1m" },   // descente
      ],
    },
  },
  // Critères d'acceptation alignés sur le SLO : le test échoue s'ils ne sont pas tenus.
  thresholds: {
    http_req_failed: ["rate<0.01"],                  // < 1 % d'erreurs (budget du SLO)
    http_req_duration: ["p(95)<500", "p(99)<1000"],  // p95 < 500 ms (seuil EcgApiHighLatency)
    checks: ["rate>0.99"],
  },
};

export default function () {
  const res = http.post(`${BASE_URL}/predict`, payload, {
    headers: { "Content-Type": "application/json" },
    tags: { route: "/predict" },
  });
  check(res, {
    "statut 200": (r) => r.status === 200,
    "8 prédictions": (r) => r.status === 200 && r.json("predictions").length === 8,
  });
}
