// import Navbar from "../ui/dashboard/navbar/navbar";
// import Sidebar from "../ui/dashboard/sidebar/sidebar";
import { useCallback, useEffect, useState } from "react";
import Card from "../ui/card/card";
import Info from "../ui/info/info";

interface Agent {
    name: string;
    lastActive: string;
    skills: string;
    status: string;
}

const Dashboard = () => {
    const [agents, setAgents] = useState<Agent[][]>([]);

    const tasks = {
        'title': "Recent Tasks",
        'header':
        [
            "Task",
            "Created",
            "Assigned to",
            "Status"
        ],
        'body':
        [
            [
                "Sales Analysis Q1",
                "16-02-2025",
                "Agent 005",
                "Completed"
            ],
            [
                "Detect Anomalies in Financial Data",
                "16-02-2025",
                "Agent 006",
                "Processing"
            ],
            [
                "Forecast Monthly Revenue",
                "16-02-2025",
                "Agent 009",
                "Running"
            ],
            [
                "Segment Customers by Behavior",
                "16-02-2025",
                "Agent 020",
                "Pending"
            ],
            [
                "Analyze Social Media Engagement",
                "16-02-2025",
                "Agent 023",
                "Pending"
            ]
        ]
    };

    const timeAgo = useCallback((date: string) => {
        const now = new Date();
        const past = new Date(date);
        const diff = now.getTime() - past.getTime();
        const minutes = Math.floor(diff / 60000);

        return minutes < 5 ? 'A few minutes ago' : minutes < 60 ? `${minutes} minutes ago` : `${Math.floor(minutes / 60)} hours ago`;
    }, []);

    const getAgents = useCallback(async () => {
        const response = await fetch('http://127.0.0.1:8000/agents/details/');
        const data: Record<string, { name: string; skills: string[]; status: string; last_heartbeat: string }>
            = await response.json();
        console.log('agents data', data);

        if (response.ok) {
            // data is a mapping of agent_id -> { name, skills, status, last_heartbeat }
            const list: Agent[][] = Object.values(data || {}).map((info) => [
                {
                    name: info.name,
                    lastActive: timeAgo(info.last_heartbeat),
                    skills: Array.isArray(info.skills)
                        ? info.skills.join(', ').replace(/_/g, ' ')
                        : '-',
                    status:
                        info.status === 'active'
                            ? 'Online'
                            : (info.status || '-')
                                  .toString()
                                  .charAt(0)
                                  .toUpperCase() + (info.status || '-')
                                  .toString()
                                  .slice(1),
                },
            ]);
            setAgents(list);
        }
    }, [timeAgo]);

    useEffect(() => {
        getAgents();
    }, [getAgents]);

    const agentHeaders: string[] = [
        "Agent",
        "Last active",
        "Skills",
        "Status"
    ];
    return (
        <div className="flex gap-3 mt-5">
            <div className="flex-3 flex flex-col gap-5">
                <div className="flex gap-5 space-between">
                    <Card
                        title="Active Agents"
                        number={agents.flat().filter((agent: Agent) => agent.status === 'Online').length}
                    />
                    <Card
                        title="Processing Tasks"
                        number={11}
                    />
                    <Card
                        title="Completed Tasks (Today)"
                        number={58}
                    />
                    <Card
                        title="Completed Tasks (Weekly)"
                        number={223}
                    />
                </div>
                <Info
                    title={"Agent Status"}
                    header={agentHeaders}
                    body={agents.map((agentRow: Agent[]) =>
                        agentRow.map((agent: Agent) => [
                            agent.name,
                            agent.lastActive,
                            agent.skills,
                            agent.status
                        ])
                    ).flat()}
                />
                <Info
                    title={tasks.title}
                    header={tasks.header}
                    body={tasks.body}
                />
            </div>
        </div>
    )
}

export default Dashboard;