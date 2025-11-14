package main

import (
    "fmt"
    "net/http"

    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

// Example counter
var requestsTotal = prometheus.NewCounterVec(
    prometheus.CounterOpts{
        Name: "app_requests_total",
        Help: "Total HTTP requests",
    },
    []string{"path"},
)

func init() {
    prometheus.MustRegister(requestsTotal)
}

func handler(w http.ResponseWriter, r *http.Request) {
    requestsTotal.WithLabelValues(r.URL.Path).Inc()
    fmt.Fprintln(w, "OK")
}

func main() {
    http.HandleFunc("/", handler)

    http.Handle("/metrics", promhttp.Handler())

    fmt.Println("Server listening on :8081")
    http.ListenAndServe(":8081", nil)
}
