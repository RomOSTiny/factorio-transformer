"""Generate dense_ln_lib.py from layernorm_gen_lib.py (rsqrt core verbatim, front/back replaced by `each` ops)."""
src = open('layernorm_gen_lib.py', encoding='utf-8').read().split('\n')


def L(a, b):
    return src[a - 1:b]


def find(prefix, start=0):
    for i in range(start, len(src)):
        if src[i].startswith(prefix):
            return i + 1
    raise SystemExit("anchor not found: " + prefix)


i_def = find("def build_layernorm(")
i_bp = find("    bp = Blueprint()")
i_ctl = find("    CTL_X = SV_X - 20")
i_vpe_end = find('    bp.add_circuit_connection(RED, "var_e", "vpe_e"')
i_xmerge = find("    x_merge_pos = ")
i_spine = find("    def spine_with_taps")
i_power = find("    # ---- power: generous lattice")

header = L(1, i_def - 1)
head_new = '''def build_dense_ln(label, gamma_real, beta_real, in_sigs, out_sigs, x_values=None):
    """Dense combinational LayerNorm over len(in_sigs) elements. The vector lives on distinct
    signals of ONE network (input port: entity xin's input); `each` arithmetic does sum, sum of
    squares, dx, prod and rescale as ONE combinator per vector op. rsqrt core (octave detector,
    oct_lower ROM, 992-word rsqrt ROM) is verbatim from build_layernorm. Output port: entity `sc`
    output network (out_sigs, beta constants summed in). Returns (bp_string, idmap, meta)."""
    N_IN = len(in_sigs)
    assert len(out_sigs) == N_IN == len(gamma_real) == len(beta_real)
    GAMMA_FP = [q(g) for g in gamma_real]
    BETA_FP = [q(b) for b in beta_real]
'''.split('\n')
mid1 = L(i_bp, i_ctl - 1)
front = '''    xin_pos = (SV_X + 0.5, SV_Y)
    bp.entities.append(ArithmeticCombinator(id="xin", position=xin_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
    bp.entities.append(ArithmeticCombinator(id="sum_e", position=(SV_X + 8.5, SV_Y + 2.5), first_operand="signal-each", operation="+", second_operand=0, output_signal="signal-E"))
    bp.add_circuit_connection(RED, "xin", "sum_e", side_1="output", side_2="input")
    bp.entities.append(ArithmeticCombinator(id="mean_e", position=(SV_X + 12.5, SV_Y + 2.5), first_operand="signal-E", operation="/", second_operand=N_IN, output_signal="signal-F"))
    bp.add_circuit_connection(RED, "sum_e", "mean_e", side_1="output", side_2="input")
    bp.entities.append(ArithmeticCombinator(id="sq_all", position=(SV_X + 4.5, SV_Y + 7.5), first_operand="signal-each", operation="*", second_operand="signal-each", output_signal="signal-G"))
    bp.add_circuit_connection(RED, "xin", "sq_all", side_1="output", side_2="input")
    bp.entities.append(ArithmeticCombinator(id="esq_e", position=(SV_X + 12.5, SV_Y + 10.5), first_operand="signal-G", operation="/", second_operand=N_IN, output_signal="signal-H"))
    bp.add_circuit_connection(RED, "sq_all", "esq_e", side_1="output", side_2="input")
    bp.entities.append(ArithmeticCombinator(id="mean_sq", position=(SV_X + 16.5, SV_Y + 2.5), first_operand="signal-F", operation="*", second_operand="signal-F", output_signal="signal-J"))
    bp.add_circuit_connection(RED, "mean_e", "mean_sq", side_1="output", side_2="input")
    bp.entities.append(ArithmeticCombinator(id="var_e", position=(SV_X + 20.5, SV_Y + 6.5), first_operand="signal-H", operation="-", second_operand="signal-J", output_signal="signal-K"))
    bp.add_circuit_connection(RED, "esq_e", "var_e", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, "mean_sq", "var_e", side_1="output", side_2="input")
    bp.entities.append(ArithmeticCombinator(id="vpe_e", position=(SV_X + 24.5, SV_Y + 6.5), first_operand="signal-K", operation="+", second_operand=EPS_SCALED, output_signal="signal-V"))
    bp.add_circuit_connection(RED, "var_e", "vpe_e", side_1="output", side_2="input")
    if x_values is not None:
        for k in range(0, N_IN, 20):
            cid = f"xin_const_{k // 20}"
            c = ConstantCombinator(id=cid, tile_position=(int(SV_X) - 4, int(SV_Y) + (k // 20) * 2))
            for j in range(k, min(k + 20, N_IN)):
                c.set_signal(index=j - k, name=in_sigs[j], count=x_values[j])
            bp.entities.append(c)
            bp.add_circuit_connection(RED, cid, "xin", side_2="input")
'''.split('\n')
mid2 = L(i_vpe_end + 1, i_xmerge - 1)
xmerge = L(i_xmerge, i_spine - 1)
out_x = []
for ln in xmerge:
    if ln.strip() == "for i in range(N_IN):":
        continue
    if 'bp.add_circuit_connection(RED, f"x_{i}_src", "x_merge"' in ln:
        ln = '    bp.add_circuit_connection(RED, "xin", "x_merge", side_1="output", side_2="input")'
    out_x.append(ln)
norm = '''    xi_pos = (NORM_X + 0.5, NORM_Y)
    bp.entities.append(ArithmeticCombinator(id="xi_local", position=xi_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
    bridge_to("x_far", x_far_pos, "xi_local", xi_pos, RED, hop=6, standoff=6)
    dx_pos = (NORM_X + 7.5, NORM_Y)
    bp.entities.append(ArithmeticCombinator(id="dx_all", position=dx_pos, first_operand="signal-each", operation="-", second_operand="signal-F", output_signal="signal-each"))
    bp.add_circuit_connection(RED, "xi_local", "dx_all", side_1="output", side_2="input")
    bridge_to("mean_local", mean_local_pos, "dx_all", dx_pos, GREEN, hop=6, standoff=6)
    prod_pos = (NORM_X + 12.5, NORM_Y)
    bp.entities.append(ArithmeticCombinator(id="prod_all", position=prod_pos, first_operand="signal-each", operation="*", second_operand="signal-R", output_signal="signal-each"))
    bp.add_circuit_connection(RED, "dx_all", "prod_all", side_1="output", side_2="input")
    bridge_to("rsqrt_local", rsqrt_local_pos, "prod_all", prod_pos, GREEN, hop=6, standoff=6)
    normed_pos = (NORM_X + 17.5, NORM_Y)
    bp.entities.append(ArithmeticCombinator(id="normed_all", position=normed_pos, first_operand="signal-each", operation="/", second_operand=SCALE, output_signal="signal-each"))
    bp.add_circuit_connection(RED, "prod_all", "normed_all", side_1="output", side_2="input")
    GX = NORM_X + 22.5
    for i in range(N_IN):
        bp.entities.append(ArithmeticCombinator(id=f"gam_{i}", position=(GX, NORM_Y + 2 * i), first_operand=in_sigs[i], operation="*", second_operand=GAMMA_FP[i], output_signal=out_sigs[i]))
        if i == 0:
            bp.add_circuit_connection(RED, "normed_all", "gam_0", side_1="output", side_2="input")
        else:
            bp.add_circuit_connection(RED, f"gam_{i - 1}", f"gam_{i}", side_1="input", side_2="input")
            bp.add_circuit_connection(RED, f"gam_{i - 1}", f"gam_{i}", side_1="output", side_2="output")
    sc_pos = (GX + 5, NORM_Y + 1)
    bp.entities.append(ArithmeticCombinator(id="sc", position=sc_pos, first_operand="signal-each", operation="/", second_operand=SCALE, output_signal="signal-each"))
    bp.add_circuit_connection(RED, "gam_0", "sc", side_1="output", side_2="input")
    for k in range(0, N_IN, 20):
        cid = f"beta_{k // 20}"
        c = ConstantCombinator(id=cid, tile_position=(int(GX) + 9, int(NORM_Y) + (k // 20) * 2))
        for j in range(k, min(k + 20, N_IN)):
            c.set_signal(index=j - k, name=out_sigs[j], count=BETA_FP[j])
        bp.entities.append(c)
        bp.add_circuit_connection(RED, cid, "sc", side_2="output")

'''.split('\n')
power = '\n'.join(L(i_power, len(src)))
k = power.index("    meta = dict(")
power = power[:k] + '''    meta = dict(total_count=len(bp.entities), N_IN=N_IN, sub_lattice_count=len(sub_lattice), empty_skipped=empty_skipped,
                gap_fill_count=gap_fill_count, worst_slack=worst_slack)
    return bp_string, idmap, meta
'''
out = '\n'.join(header) + '\n' + '\n'.join(head_new) + '\n'.join(mid1) + '\n' + '\n'.join(front) + '\n'.join(mid2) + '\n' + '\n'.join(out_x) + '\n' + '\n'.join(norm) + '\n' + power
out = out.replace('"""\nReusable generator for the parametrized LayerNorm block', '"""\n[DENSE variant, generated by make_dense_ln.py from layernorm_gen_lib.py: build_dense_ln]\nReusable generator for the parametrized LayerNorm block', 1)
open('dense_ln_lib.py', 'w', encoding='utf-8').write(out)
print("written", len(out.split('\n')), "lines")
