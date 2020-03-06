var lagopusChartColors = {
    red: 'rgb(255, 99, 132)',
    orange: 'rgb(255, 159, 64)',
    yellow: 'rgb(255, 205, 86)',
    green: 'rgb(75, 192, 192)',
    blue: 'rgb(54, 162, 235)',
    purple: 'rgb(153, 102, 255)',
    grey: 'rgb(201, 203, 207)',
    white: 'rgb(255, 255, 255)'
};

/*
 * For each dataset, if we have no data, get it all; if we have data,
 * get all data since the timestamp of the most recent data point
 */
function lagopus_update_chart(chart, jobid) {
    chart.data.datasets.forEach((dataset) => {
        let since = null;
        if (dataset.data.length != 0) {
            since = dataset.data[dataset.data.length - 1].x.toISOString();
        }
        $.ajax({
            type: "get",
            url: "api/jobs/" + jobid + "/stats"  + (since != null ? "?since=" + since : ''),
            success: function(data) {
                console.log(data);
                if (data.length == 0)
		    return;
                newdata = data.map(function(point) {
                    return {
                        x: new moment(point['time']),
                        y: point[dataset['influx_column']]
                    };
                });
                dataset.data = dataset.data.concat(newdata.slice(1));
                chart.update();
            }
        });
    });
}

/*
 * Specify a Canvas element to turn it into a live chart of execs / sec
 */
function lagopus_job_aflstat(ctx, jobid) {
    var color = Chart.helpers.color;

    var chart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                influx_column: 'mean_total_paths',
                label: 'Total paths',
                pointRadius: 1,
                backgroundColor: color(lagopusChartColors.grey).alpha(0.3).rgbString(),
                fill: true,
                data: []
            },
            {
                influx_column: 'mean_current_path',
                label: 'Current path',
                pointRadius: 1,
                backgroundColor: color(lagopusChartColors.white).alpha(0.4).rgbString(),
                fill: true,
                data: []
            },
            {
                influx_column: 'mean_pending',
                label: 'Pending paths',
                pointRadius: 1,
                backgroundColor: color(lagopusChartColors.blue).alpha(0.5).rgbString(),
                fill: true,
                data: []
            },
            {
                influx_column: 'mean_pending_fav',
                label: 'Pending favored paths',
                pointRadius: 1,
                backgroundColor: color(lagopusChartColors.red).alpha(0.8).rgbString(),
                fill: true,
                data: []
            }]
        },
        options: {
            maintainAspectRatio: false,
            scales: {
                yAxes: [{
                    ticks: {
                        suggestedMin: 0,
                        suggestedMax: 500,
                    }
                }],
                xAxes: [{
                    type: 'time',
                    time: {
                        displayFormats: {
                            second: 'h:mm:ss'
                        }
                    },
                    distribution: 'series',
                    bounds: 'data'
                }]
            }
        }
    });

    function updategraph() {
        lagopus_update_chart(chart, jobid);
        setTimeout(function() {
            updategraph();
        },
        5000);
    }

    updategraph();
}

function lagopus_job_aflperf(ctx, jobid) {
    var color = Chart.helpers.color;

    var chart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                label: 'Execs / sec',
                influx_column: 'mean_execs_per_sec',
                pointRadius: 1,
                // borderColor: color(lagopusChartColors.blue).rgbString(),
                backgroundColor: color(lagopusChartColors.blue).alpha(0.6).rgbString(),
                fill: true,
                data: [],
                yAxisID: "y-axis-eps"
            }, {
                label: 'Memory',
                influx_column: 'mean_memory',
                pointRadius: 1,
                borderColor: color(lagopusChartColors.orange).alpha(0.4).rgbString(),
                backgroundColor: color(lagopusChartColors.orange).alpha(0.4).rgbString(),
                fill: false,
                data: [],
                yAxisID: "y-axis-memory"
            }]
        },
        options: {
            maintainAspectRatio: false,
            scales: {
                yAxes: [{
                    id: "y-axis-eps",
                    type: "linear",
                    display: true,
                    position: "left",
                    ticks: {
                        suggestedMin: 0,
                        suggestedMax: 500,
                    }
                }, {
                    id: "y-axis-memory",
                    type: "linear",
                    display: true,
                    position: "right",
                    ticks: {
                        suggestedMin: 0,
                        suggestedMax: 5000,
                    },
                    gridLines: {
                        drawOnChartArea: false
                    },
                }],
                xAxes: [{
                    type: 'time',
                    time: {
                        displayFormats: {
                            second: 'h:mm:ss'
                        }
                    },
                    distribution: 'series',
                    bounds: 'data'
                }]
            }
        }
    });

    function updategraph() {
        lagopus_update_chart(chart, jobid);
        setTimeout(updategraph, 5000);
    }

    updategraph();
}
